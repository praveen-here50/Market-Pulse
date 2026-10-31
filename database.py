"""MarketPulse Phase 7: the SQLite database that holds the watchlist, trades and price cache.

SQLite comes with Python and keeps everything in one file, in a folder git ignores.
Set MARKETPULSE_DATA_FOLDER to use another folder, such as a scratch one for testing.

The first time the database is created, the Phase 6 JSON files are imported in the
same transaction. So either everything arrives or nothing does, and a damaged file
raises an error instead of counting as empty. The JSON files are left as they were
and are never read again.
"""

import json
import os
import sqlite3
from contextlib import closing, contextmanager
from pathlib import Path

from market_data.instruments import INSTRUMENTS

DATA_FOLDER = Path(
    os.environ.get("MARKETPULSE_DATA_FOLDER", Path(__file__).parent / "data" / "user")
)
DATABASE_FILE = "marketpulse.db"
WATCHLIST_FILE = "watchlist.json"
TRADES_FILE = "trades.json"

# How long to wait for another thread's write before giving up with an error.
BUSY_SECONDS = 10

# Stored inside the file as `user_version`. 0 means the tables do not exist yet.
SCHEMA_VERSION = 2

# STRICT makes SQLite refuse a value of the wrong type instead of storing it anyway.
# `position` keeps rows in the order they were entered, which decides how trades on
# the same date replay. The hidden rowid could change, so it is not relied on.
SCHEMA = """
CREATE TABLE watchlist (
    position INTEGER PRIMARY KEY,
    ticker TEXT NOT NULL UNIQUE,
    is_fno INTEGER NOT NULL CHECK (is_fno IN (0, 1))
) STRICT;

CREATE TABLE trades (
    position INTEGER PRIMARY KEY,
    id TEXT NOT NULL UNIQUE,
    ticker TEXT NOT NULL REFERENCES watchlist (ticker),
    side TEXT NOT NULL CHECK (side IN ('buy', 'sell')),
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    price REAL NOT NULL CHECK (price > 0),
    trade_date TEXT NOT NULL
) STRICT;

CREATE TABLE price_downloads (
    ticker TEXT NOT NULL,
    period TEXT NOT NULL,
    source TEXT NOT NULL,
    downloaded_at TEXT NOT NULL,
    PRIMARY KEY (ticker, period)
) STRICT;

CREATE TABLE price_bars (
    ticker TEXT NOT NULL,
    period TEXT NOT NULL,
    day TEXT NOT NULL,
    open REAL NOT NULL,
    high REAL NOT NULL,
    low REAL NOT NULL,
    close REAL NOT NULL,
    adj_close REAL,
    volume INTEGER NOT NULL,
    PRIMARY KEY (ticker, period, day),
    FOREIGN KEY (ticker, period) REFERENCES price_downloads (ticker, period) ON DELETE CASCADE
) STRICT;
"""


# Added in Phase 11. `was_met` remembers the last result, so an alert fires when its
# condition becomes true, not on every day it stays true.
VERSION_2 = """
CREATE TABLE alerts (
    position INTEGER PRIMARY KEY,
    id TEXT NOT NULL UNIQUE,
    ticker TEXT NOT NULL REFERENCES watchlist (ticker),
    kind TEXT NOT NULL CHECK (
        kind IN ('close_above', 'close_below', 'move_at_least', 'rsi_above', 'rsi_below')
    ),
    threshold REAL NOT NULL CHECK (threshold > 0),
    was_met INTEGER NOT NULL DEFAULT 0 CHECK (was_met IN (0, 1)),
    last_checked_bar TEXT
) STRICT;
"""


def default_watchlist():
    return [
        {"ticker": ticker, "is_fno": instrument.is_fno}
        for ticker, instrument in INSTRUMENTS.items()
    ]


def read_json_file(name, default):
    path = DATA_FOLDER / name
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def import_json_files(connection):
    """Copy the Phase 6 files in, or the default stocks if there are none."""
    stocks = read_json_file(WATCHLIST_FILE, default_watchlist())
    trades = read_json_file(TRADES_FILE, [])

    # The database would refuse these too, but without saying which stock it was.
    followed = {stock["ticker"] for stock in stocks}
    unknown = sorted({trade["ticker"] for trade in trades} - followed)
    if unknown:
        raise ValueError(f"{TRADES_FILE} has trades for stocks not on the watchlist: {unknown}")

    connection.executemany(
        "INSERT INTO watchlist (ticker, is_fno) VALUES (:ticker, :is_fno)", stocks
    )
    connection.executemany(
        "INSERT INTO trades (id, ticker, side, quantity, price, trade_date) "
        "VALUES (:id, :ticker, :side, :quantity, :price, :trade_date)",
        trades,
    )


def schema_version(connection):
    return connection.execute("PRAGMA user_version").fetchone()[0]


def prepare(connection):
    """Create or upgrade the tables. A failure changes nothing, so it can retry.

    Each step moves one version up and keeps every existing row, so a database from
    any earlier version arrives here. The file holds real trades: never recreate it.
    """
    if schema_version(connection) == SCHEMA_VERSION:
        return

    connection.execute("BEGIN IMMEDIATE")
    # Another thread may have finished this while we waited for the write lock.
    version = schema_version(connection)
    if version > SCHEMA_VERSION:
        raise RuntimeError(f"Database is version {version}, this code expects {SCHEMA_VERSION}")
    if version < 1:
        connection.executescript(SCHEMA)
        import_json_files(connection)
    if version < 2:
        connection.executescript(VERSION_2)
    connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    connection.execute("COMMIT")


def connect():
    """Open the database. Each call gets its own connection, so threads never share one."""
    DATA_FOLDER.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(
        DATA_FOLDER / DATABASE_FILE, timeout=BUSY_SECONDS, autocommit=True
    )
    try:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        prepare(connection)
    except Exception:
        connection.close()
        raise
    return connection


@contextmanager
def transaction():
    """Run a block that saves everything or nothing.

    BEGIN IMMEDIATE takes the write lock at the start, so two saves cannot both read
    the same old rows. If the block raises, the connection closes without COMMIT and
    SQLite undoes the changes.
    """
    with closing(connect()) as connection:
        connection.execute("BEGIN IMMEDIATE")
        yield connection
        connection.execute("COMMIT")

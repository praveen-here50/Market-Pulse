"""MarketPulse Phase 6: keep the watchlist and trades in JSON files on this computer.

The files live in data/user, which git ignores, so holdings are never committed.
Phase 7 replaces this module with a database.

A damaged file raises an error instead of counting as empty. Otherwise the next
save would quietly replace someone's trades with a nearly empty list.
"""

import json
import threading
import uuid
from pathlib import Path

from market_data.instruments import INSTRUMENTS, Instrument

DATA_FOLDER = Path(__file__).parent / "data" / "user"
WATCHLIST_FILE = "watchlist.json"
TRADES_FILE = "trades.json"

# FastAPI runs requests in several threads. Without this lock, two saves at once
# could each start from the same old file, and one change would be lost.
_write_lock = threading.Lock()


class Rejected(Exception):
    """The request conflicts with what is already saved."""


def read_json(name, default):
    path = DATA_FOLDER / name
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(name, value):
    """Save through a temporary file, so a crash cannot leave a half-written file."""
    DATA_FOLDER.mkdir(parents=True, exist_ok=True)
    temporary = DATA_FOLDER / f"{name}.tmp"
    temporary.write_text(json.dumps(value, indent=2), encoding="utf-8")
    temporary.replace(DATA_FOLDER / name)


def _default_watchlist():
    return [
        {"ticker": ticker, "is_fno": instrument.is_fno}
        for ticker, instrument in INSTRUMENTS.items()
    ]


def load_watchlist():
    """Return the followed stocks as {ticker: Instrument}, oldest first."""
    return {
        stock["ticker"]: Instrument(stock["ticker"].removesuffix(".NS"), stock["is_fno"])
        for stock in read_json(WATCHLIST_FILE, _default_watchlist())
    }


def add_stock(ticker, is_fno):
    with _write_lock:
        stocks = read_json(WATCHLIST_FILE, _default_watchlist())
        if any(stock["ticker"] == ticker for stock in stocks):
            raise Rejected(f"{ticker} is already on the watchlist")
        write_json(WATCHLIST_FILE, [*stocks, {"ticker": ticker, "is_fno": is_fno}])


def remove_stock(ticker):
    """Remove a stock, unless trades still need it for valuing the portfolio."""
    with _write_lock:
        if any(trade["ticker"] == ticker for trade in load_trades()):
            raise Rejected(f"{ticker} has trades. Delete them before removing it")
        stocks = read_json(WATCHLIST_FILE, _default_watchlist())
        write_json(WATCHLIST_FILE, [stock for stock in stocks if stock["ticker"] != ticker])


def load_trades():
    return read_json(TRADES_FILE, [])


def add_trade(trade, check):
    """Save a trade, if `check` accepts the full list with it included."""
    with _write_lock:
        trades = [*load_trades(), {"id": uuid.uuid4().hex, **trade}]
        check(trades)
        write_json(TRADES_FILE, trades)
        return trades[-1]


def delete_trade(trade_id, check):
    """Delete a trade, if `check` accepts the list without it. Return False if not found."""
    with _write_lock:
        trades = load_trades()
        remaining = [trade for trade in trades if trade["id"] != trade_id]
        if len(remaining) == len(trades):
            return False
        check(remaining)
        write_json(TRADES_FILE, remaining)
        return True

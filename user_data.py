"""MarketPulse Phase 6: keep the watchlist and trades on this computer.

Since Phase 7 they live in the SQLite database opened by database.py, in a folder
git ignores, so holdings are never committed.
"""

import uuid
from contextlib import closing

import database
from market_data.instruments import Instrument


class Rejected(Exception):
    """The request conflicts with what is already saved."""


def read_trades(connection):
    rows = connection.execute(
        "SELECT id, ticker, side, quantity, price, trade_date FROM trades ORDER BY position"
    )
    return [dict(row) for row in rows]


def load_watchlist():
    """Return the followed stocks as {ticker: Instrument}, oldest first."""
    with closing(database.connect()) as connection:
        rows = connection.execute("SELECT ticker, is_fno FROM watchlist ORDER BY position")
        return {
            row["ticker"]: Instrument(row["ticker"].removesuffix(".NS"), bool(row["is_fno"]))
            for row in rows
        }


def add_stock(ticker, is_fno):
    with database.transaction() as connection:
        found = connection.execute("SELECT 1 FROM watchlist WHERE ticker = ?", (ticker,))
        if found.fetchone():
            raise Rejected(f"{ticker} is already on the watchlist")
        connection.execute(
            "INSERT INTO watchlist (ticker, is_fno) VALUES (?, ?)", (ticker, is_fno)
        )


def remove_stock(ticker):
    """Remove a stock, unless trades still need it for valuing the portfolio."""
    with database.transaction() as connection:
        found = connection.execute("SELECT 1 FROM trades WHERE ticker = ?", (ticker,))
        if found.fetchone():
            raise Rejected(f"{ticker} has trades. Delete them before removing it")
        found = connection.execute("SELECT 1 FROM alerts WHERE ticker = ?", (ticker,))
        if found.fetchone():
            raise Rejected(f"{ticker} has alerts. Delete them before removing it")
        connection.execute("DELETE FROM watchlist WHERE ticker = ?", (ticker,))


def load_trades():
    with closing(database.connect()) as connection:
        return read_trades(connection)


def add_trade(trade, check):
    """Save a trade, if `check` accepts the full list with it included."""
    saved = {"id": uuid.uuid4().hex, **trade}
    with database.transaction() as connection:
        check([*read_trades(connection), saved])
        connection.execute(
            "INSERT INTO trades (id, ticker, side, quantity, price, trade_date) "
            "VALUES (:id, :ticker, :side, :quantity, :price, :trade_date)",
            saved,
        )
    return saved


def delete_trade(trade_id, check):
    """Delete a trade, if `check` accepts the list without it. Return False if not found."""
    with database.transaction() as connection:
        trades = read_trades(connection)
        remaining = [trade for trade in trades if trade["id"] != trade_id]
        if len(remaining) == len(trades):
            return False
        check(remaining)
        connection.execute("DELETE FROM trades WHERE id = ?", (trade_id,))
        return True

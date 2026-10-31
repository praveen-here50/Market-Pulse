"""MarketPulse Phase 7: reuse a recent download instead of asking Yahoo again.

A saved copy is still delayed daily data, so the API labels it with its download
time. It is only used while all of these hold:

- It is younger than MAX_AGE.
- It was not downloaded before a close that has since passed. Otherwise a bar saved
  during the session would be read afterwards as that day's finished bar.
- It passes the caller's `check` again, which also catches data that became stale.

Only a clean result from the first provider is saved. A fallback answer would hide
Yahoo's recovery for MAX_AGE, and its failures would be missing when served again.

Splits are never cached. An old split list would give a wrong share count.
"""

from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timedelta

import pandas as pd

import database
import fetch_prices
from market_data.service import fetch_with_fallback

MAX_AGE = timedelta(minutes=15)

# The columns the API and calculations use, with their names in the database.
# Yahoo's other columns, such as Dividends, are not saved.
COLUMNS = {
    "Open": "open",
    "High": "high",
    "Low": "low",
    "Close": "close",
    "Adj Close": "adj_close",
    "Volume": "volume",
}


@dataclass
class CachedResult:
    history: pd.DataFrame | None
    source: str | None
    failures: list
    downloaded_at: pd.Timestamp | None = None


def is_usable(downloaded_at, now, market_close):
    """Return True if a saved copy is recent and no session closed since it was made."""
    if not timedelta(0) <= now - downloaded_at < MAX_AGE:
        return False
    today_close = pd.Timestamp(datetime.combine(now.date(), market_close), tz=now.tz)
    return not downloaded_at < today_close <= now


def load(ticker, period, now, market_close):
    """Return a usable saved copy, or None."""
    with closing(database.connect()) as connection:
        download = connection.execute(
            "SELECT source, downloaded_at FROM price_downloads WHERE ticker = ? AND period = ?",
            (ticker, period),
        ).fetchone()
        if download is None:
            return None

        downloaded_at = pd.Timestamp(download["downloaded_at"])
        if not is_usable(downloaded_at, now, market_close):
            return None

        rows = connection.execute(
            f"SELECT day, {', '.join(COLUMNS.values())} FROM price_bars "
            "WHERE ticker = ? AND period = ? ORDER BY day",
            (ticker, period),
        ).fetchall()

    table = pd.DataFrame([tuple(row) for row in rows], columns=["Date", *COLUMNS])
    index = pd.DatetimeIndex(table.pop("Date")).tz_localize(fetch_prices.MARKET_TIMEZONE)
    history = table.astype({"Adj Close": float}).set_index(index)
    return CachedResult(history, download["source"], [], downloaded_at)


def save(ticker, period, history, source, now):
    """Replace the saved copy of this download. Old bars go with it (ON DELETE CASCADE)."""
    bars = history.reindex(columns=list(COLUMNS))
    days = [f"{day:%Y-%m-%d}" for day in history.index]
    rows = zip(days, *(bars[column].tolist() for column in COLUMNS))

    with database.transaction() as connection:
        connection.execute(
            "DELETE FROM price_downloads WHERE ticker = ? AND period = ?", (ticker, period)
        )
        connection.execute(
            "INSERT INTO price_downloads (ticker, period, source, downloaded_at) "
            "VALUES (?, ?, ?, ?)",
            (ticker, period, source, now.isoformat()),
        )
        connection.executemany(
            f"INSERT INTO price_bars (ticker, period, day, {', '.join(COLUMNS.values())}) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [(ticker, period, *row) for row in rows],
        )


def fetch(ticker, period, check, now, market_close, use_saved=True):
    """Return a usable saved copy, or download and save a new one."""
    saved = load(ticker, period, now, market_close) if use_saved else None
    if saved is not None and not check(saved.history):
        return saved

    result = fetch_with_fallback(ticker, period, check)
    if result.history is not None and not result.failures:
        save(ticker, period, result.history, result.source, now)
    return CachedResult(result.history, result.source, result.failures)

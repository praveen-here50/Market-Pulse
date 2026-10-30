"""MarketPulse Phase 1: download and validate daily prices for four NSE stocks.

Run with:  python fetch_prices.py
Exit code: 0 if every symbol passed validation, 1 if any symbol failed.
"""

import sys
from datetime import timedelta

import pandas as pd

from market_data.instruments import INSTRUMENTS, market_close_for
from market_data.service import fetch_with_fallback

SYMBOLS = list(INSTRUMENTS)  # .NS means the NSE listing
PERIOD = "1mo"
ROWS_TO_SHOW = 5

MARKET_TIMEZONE = "Asia/Kolkata"

PRICE_COLUMNS = ["Open", "High", "Low", "Close"]
REQUIRED_COLUMNS = [*PRICE_COLUMNS, "Volume"]

# The latest bar may be this old before we call it stale. Five calendar days
# covers a weekend plus a market holiday without hiding a real outage.
MAX_AGE = timedelta(days=5)

# Yahoo stores prices at low precision (1204.300049 for 1204.30), so comparing
# High and Close exactly could reject a perfectly good row.
PRICE_TOLERANCE = 0.01


def validate_history(history, now):
    """Return a list of problems found in the data. An empty list means it passed."""
    if history.empty:
        return ["no rows returned (unknown symbol, or the provider had no data)"]

    missing = [column for column in REQUIRED_COLUMNS if column not in history.columns]
    if missing:
        return [f"missing columns: {missing}"]

    problems = []

    if history[REQUIRED_COLUMNS].isna().any(axis=None):
        problems.append("contains missing values")
    if (history[PRICE_COLUMNS] <= 0).any(axis=None):
        problems.append("contains zero or negative prices")
    if (history["Volume"] < 0).any():
        problems.append("contains negative volume")

    bar_high = history[["Open", "Close"]].max(axis=1)
    bar_low = history[["Open", "Close"]].min(axis=1)
    if (history["High"] < bar_high - PRICE_TOLERANCE).any():
        problems.append("High is below Open or Close in at least one row")
    if (history["Low"] > bar_low + PRICE_TOLERANCE).any():
        problems.append("Low is above Open or Close in at least one row")

    if history.index.has_duplicates:
        problems.append("contains duplicate dates")
    if not history.index.is_monotonic_increasing:
        problems.append("dates are not in ascending order")

    latest = history.index.max()
    if latest > now:
        problems.append(f"latest timestamp {latest} is in the future")
    elif now - latest > MAX_AGE:
        problems.append(f"data is stale: latest bar is from {latest.date()}")

    return problems


def is_bar_in_progress(latest, now, market_close):
    """Return True if the newest bar belongs to a session that has not closed yet."""
    return latest.date() == now.date() and now.time() < market_close


def describe_latest_bar(latest, now, market_close):
    """Say whether the newest bar is final or still changing during today's session."""
    if is_bar_in_progress(latest, now, market_close):
        return "IN PROGRESS: today's session has not closed, values will change"
    return "complete daily bar"


def print_report(symbol, history, now, source):
    """Print the most recent rows and the latest timestamp for a validated symbol."""
    latest = history.index.max()

    table = history[REQUIRED_COLUMNS].tail(ROWS_TO_SHOW).copy()
    table.index = table.index.date
    table.index.name = "Date"

    print(f"\n{symbol} | source: {source}")
    print(table.to_string(float_format="{:.2f}".format))
    print(f"Latest available timestamp: {latest}")
    print(f"Latest bar status:          {describe_latest_bar(latest, now, market_close_for(symbol))}")


def main():
    now = pd.Timestamp.now(tz=MARKET_TIMEZONE)
    failed = {}

    print(f"MarketPulse Phase 1 | fetched at {now:%Y-%m-%d %H:%M:%S %Z}")
    print("Daily bars, not live quotes. Neither provider is a real-time exchange feed.")
    print("Prices in INR. Timestamps mark the trading date, not the time of the last trade.")

    for symbol in SYMBOLS:
        result = fetch_with_fallback(symbol, PERIOD, lambda table: validate_history(table, now))
        if result.history is None:
            failed[symbol] = result.failures
        else:
            print_report(symbol, result.history, now, result.source)
            for failure in result.failures:
                print(f"Fallback used because {failure}")

    print(f"\nValidation: {len(SYMBOLS) - len(failed)} of {len(SYMBOLS)} symbols passed")
    for symbol, problems in failed.items():
        print(f"  FAILED {symbol}: {'; '.join(problems)}")

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

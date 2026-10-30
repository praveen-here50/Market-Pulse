"""MarketPulse Phase 1: download and validate daily prices for four NSE stocks.

Run with:  python fetch_prices.py
Exit code: 0 if every symbol passed validation, 1 if any symbol failed.
"""

import sys
import warnings
from datetime import time, timedelta

import pandas as pd
import yfinance as yf

# yfinance 1.7 triggers this deprecation inside its own code on pandas 3.1.
# Only this category from yfinance is hidden, so our own warnings still show.
warnings.filterwarnings("ignore", category=pd.errors.Pandas4Warning, module=r"yfinance\.")

SYMBOLS = ["RELIANCE.NS", "TCS.NS", "INFY.NS", "HDFCBANK.NS"]  # .NS means the NSE listing
PERIOD = "1mo"
INTERVAL = "1d"
ROWS_TO_SHOW = 5

MARKET_TIMEZONE = "Asia/Kolkata"

# Since 3 Aug 2026, F&O stocks stop continuous trading at 15:15 and get their
# closing price from an auction ending at 15:35. All our symbols are F&O stocks.
# Non-F&O stocks still close at 15:30, so this must be revisited in Phase 3.
MARKET_CLOSE = time(15, 35)

PRICE_COLUMNS = ["Open", "High", "Low", "Close"]
REQUIRED_COLUMNS = [*PRICE_COLUMNS, "Volume"]

# The latest bar may be this old before we call it stale. Five calendar days
# covers a weekend plus a market holiday without hiding a real outage.
MAX_AGE = timedelta(days=5)

# Yahoo stores prices at low precision (1204.300049 for 1204.30), so comparing
# High and Close exactly could reject a perfectly good row.
PRICE_TOLERANCE = 0.01


def fetch_history(symbol):
    """Return Yahoo's daily bars for one symbol as a DataFrame.

    auto_adjust=False keeps Close as the traded close. With the default (True),
    past prices are lowered for dividends and no longer match the exchange's
    published values.

    A wrong symbol does NOT raise an exception here: yfinance returns an empty
    table, so callers must always validate what they get back.
    """
    return yf.Ticker(symbol).history(period=PERIOD, interval=INTERVAL, auto_adjust=False)


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


def describe_latest_bar(latest, now):
    """Say whether the newest bar is final or still changing during today's session."""
    if latest.date() == now.date() and now.time() < MARKET_CLOSE:
        return "IN PROGRESS: today's session has not closed, values will change"
    return "complete daily bar"


def print_report(symbol, history, now):
    """Print the most recent rows and the latest timestamp for a validated symbol."""
    latest = history.index.max()

    table = history[REQUIRED_COLUMNS].tail(ROWS_TO_SHOW).copy()
    table.index = table.index.date
    table.index.name = "Date"

    print(f"\n{symbol}")
    print(table.to_string(float_format="{:.2f}".format))
    print(f"Latest available timestamp: {latest}")
    print(f"Latest bar status:          {describe_latest_bar(latest, now)}")


def main():
    now = pd.Timestamp.now(tz=MARKET_TIMEZONE)
    failed = {}

    print(f"MarketPulse Phase 1 | fetched at {now:%Y-%m-%d %H:%M:%S %Z}")
    print("Source: Yahoo Finance via yfinance (unofficial). Daily bars, not live quotes.")
    print("Prices in INR. Timestamps mark the trading date, not the time of the last trade.")

    for symbol in SYMBOLS:
        # One broken symbol should not stop the others from being reported.
        try:
            history = fetch_history(symbol)
            problems = validate_history(history, now)
        except Exception as error:
            problems = [f"download failed: {type(error).__name__}: {error}"]

        if problems:
            failed[symbol] = problems
        else:
            print_report(symbol, history, now)

    print(f"\nValidation: {len(SYMBOLS) - len(failed)} of {len(SYMBOLS)} symbols passed")
    for symbol, problems in failed.items():
        print(f"  FAILED {symbol}: {'; '.join(problems)}")

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

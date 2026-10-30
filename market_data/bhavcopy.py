"""Daily bars from NSE bhavcopy files that the user downloaded by hand.

This module reads local files and must never download them. NSE's Terms of Use
prohibit systematic or automated data collection from its website, while its
copyright policy allows downloads for personal, non-commercial or educational use.

Unlike Yahoo's, these prices are NOT adjusted for splits and there is no Adj Close.
"""

from pathlib import Path

import pandas as pd

BHAVCOPY_FOLDER = Path("data") / "bhavcopy"
EQUITY_SERIES = "EQ"
MARKET_TIMEZONE = "Asia/Kolkata"
PRICE_TOLERANCE = 0.01

PERIODS = {"1mo": pd.DateOffset(months=1), "1y": pd.DateOffset(years=1)}

COLUMN_NAMES = {
    "OPEN_PRICE": "Open",
    "HIGH_PRICE": "High",
    "LOW_PRICE": "Low",
    "CLOSE_PRICE": "Close",
    "TTL_TRD_QNTY": "Volume",
    "PREV_CLOSE": "Prev Close",
}


class ProviderError(Exception):
    """A provider has data, but it cannot be used safely."""


def read_file(path, nse_symbol):
    """Return the equity row for one symbol from one bhavcopy file."""
    table = pd.read_csv(path, skipinitialspace=True)
    table.columns = table.columns.str.strip()
    is_stock = table["SYMBOL"].str.strip() == nse_symbol
    is_equity = table["SERIES"].str.strip() == EQUITY_SERIES
    return table[is_stock & is_equity]


class BhavcopyFileProvider:
    name = "NSE bhavcopy file"

    def __init__(self, folder=BHAVCOPY_FOLDER):
        self.folder = Path(folder)

    def read_bars(self, ticker):
        """Return every bar for one symbol found in the folder, oldest first.

        The date comes from inside each file, never from its name. NSE also
        serves the previous session under a non-trading day's name: its
        15 Jan 2026 file holds 14 Jan data. Such repeats are dropped here.
        """
        nse_symbol = ticker.removesuffix(".NS")
        rows = [read_file(path, nse_symbol) for path in sorted(self.folder.glob("*.csv"))]
        rows = [row for row in rows if not row.empty]
        if not rows:
            return pd.DataFrame()

        table = pd.concat(rows)
        dates = pd.to_datetime(table["DATE1"].str.strip(), format="%d-%b-%Y")
        bars = table.set_index(pd.DatetimeIndex(dates).tz_localize(MARKET_TIMEZONE))
        bars = bars.rename(columns=COLUMN_NAMES)[list(COLUMN_NAMES.values())]
        return bars[~bars.index.duplicated()].sort_index()

    def fetch_daily(self, ticker, period):
        """Return bars for one continuous period, or raise if they cannot be joined.

        On a split, NSE lowers PREV_CLOSE but older files keep the old prices, so
        the table would show a crash that never happened. A missing file looks
        the same: PREV_CLOSE stops matching the close before it. Either way the
        table is not safe to calculate on.
        """
        bars = self.read_bars(ticker)
        if bars.empty:
            return bars

        bars = bars[bars.index > bars.index[-1] - PERIODS[period]]
        mismatch = (bars["Prev Close"] - bars["Close"].shift()).abs() > PRICE_TOLERANCE
        if mismatch.any():
            date = bars.index[mismatch][0]
            raise ProviderError(
                f"PREV_CLOSE does not join on {date:%Y-%m-%d}: a file is missing or "
                "there was a corporate action"
            )
        return bars.drop(columns="Prev Close")

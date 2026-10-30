"""Daily bars from Yahoo Finance through yfinance, an unofficial library."""

import warnings

import pandas as pd
import yfinance as yf

# yfinance 1.7 triggers this deprecation inside its own code on pandas 3.1.
# Only this category from yfinance is hidden, so our own warnings still show.
warnings.filterwarnings("ignore", category=pd.errors.Pandas4Warning, module=r"yfinance\.")

INTERVAL = "1d"


class YahooProvider:
    name = "Yahoo (unofficial)"

    def fetch_daily(self, ticker, period):
        """Return Yahoo's daily bars for one symbol as a DataFrame.

        auto_adjust=False keeps Close as the traded close. With the default (True),
        past prices are lowered for dividends and no longer match the exchange's
        published values.

        A wrong symbol does NOT raise an exception here: yfinance returns an empty
        table, so callers must always validate what they get back.
        """
        return yf.Ticker(ticker).history(period=period, interval=INTERVAL, auto_adjust=False)

    def fetch_splits(self, ticker, since):
        """Return splits and bonus issues from a date on, as {ISO date: ratio}.

        This reads history() rather than the .splits property because rows with
        no splits and an empty table can be told apart: empty means the download
        failed, and an empty dict must only ever mean "no splits".
        """
        history = yf.Ticker(ticker).history(start=since, interval=INTERVAL, auto_adjust=False)
        if history.empty:
            raise ConnectionError(f"no history returned for {ticker} since {since}")
        splits = history.loc[history["Stock Splits"] != 0, "Stock Splits"]
        return {f"{day:%Y-%m-%d}": float(ratio) for day, ratio in splits.items()}

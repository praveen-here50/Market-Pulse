"""Made-up prices for the public demo. Nothing here is market data.

Stocks have invented DEMO names, so no number can be mistaken for a real company's
price. A real ticker is refused rather than given an invented price.
"""

import random

import pandas as pd

from market_data.instruments import Instrument

TIMEZONE = "Asia/Kolkata"
SOURCE = "SAMPLE DATA (made up, not market prices)"
BARS = {"1mo": 22, "1y": 250}
LATEST_BARS = max(BARS.values())

# Ticker: (price the walk starts from, whether it trades in F&O).
STOCKS = {
    "DEMO-ALPHA.NS": (1250.0, True),
    "DEMO-BETA.NS": (640.0, False),
    "DEMO-GAMMA.NS": (3120.0, True),
    "DEMO-DELTA.NS": (215.0, False),
}

INSTRUMENTS = {
    ticker: Instrument(ticker.removesuffix(".NS"), is_fno)
    for ticker, (_, is_fno) in STOCKS.items()
}


def random_walk(ticker):
    """Return made-up daily rows. The same ticker always gives the same prices."""
    generator = random.Random(ticker)
    close = STOCKS[ticker][0]
    rows = []
    for _ in range(LATEST_BARS):
        open_price = close
        close = round(open_price * (1 + generator.gauss(0.0005, 0.014)), 2)
        rows.append(
            {
                "Open": open_price,
                "High": round(max(open_price, close) * (1 + generator.uniform(0, 0.006)), 2),
                "Low": round(min(open_price, close) * (1 - generator.uniform(0, 0.006)), 2),
                "Close": close,
                "Adj Close": close,
                "Volume": generator.randrange(100_000, 2_000_000),
            }
        )
    return rows


class SampleProvider:
    name = SOURCE

    def fetch_daily(self, ticker, period):
        if ticker not in STOCKS:
            raise ValueError(f"the demo only has sample stocks: {', '.join(STOCKS)}")

        today = pd.Timestamp.now(tz=TIMEZONE).normalize().tz_localize(None)
        days = pd.bdate_range(end=today, periods=LATEST_BARS).tz_localize(TIMEZONE)
        return pd.DataFrame(random_walk(ticker), index=days).tail(BARS[period])

    def fetch_splits(self, ticker, since):
        return {}

    def fetch_news(self, ticker, limit):
        published = int(pd.Timestamp.now(tz=TIMEZONE).timestamp())
        name = ticker.removesuffix(".NS")
        titles = [
            f"SAMPLE headline: {name} is a made-up company",
            f"SAMPLE headline: this shows where real articles about {name} would appear",
        ]
        return [
            {
                "title": title,
                "publisher": "Sample publisher",
                "published_at": published,
                "link": "https://example.com/",
            }
            for title in titles
        ][:limit]

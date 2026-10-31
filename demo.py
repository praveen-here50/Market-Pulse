"""Switch MarketPulse into its public demo: made-up prices and nothing private.

The demo is safe to show because it cannot reach anything real:

- Prices and news come only from market_data/sample.py, so no provider is contacted.
- The database is a new temporary folder, so it is empty of real trades and each
  restart resets what viewers changed.
- Keys are removed and .env is not read, so Gemini and Telegram cannot be used.
- The dashboard talks to the API inside this program, so no port is opened for it.
"""

import os
import tempfile
from pathlib import Path

NOTICE = (
    "Demo with SAMPLE DATA. Every company, price and headline here is made up. "
    "Nothing is real market data, and nothing here is financial advice."
)

SECRET_NAMES = ("GEMINI_API_KEY", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID")

_active = False


def seed_sample_portfolio():
    """Add a few sample trades and alerts, so no page starts empty."""
    import alerts
    import pandas as pd
    import user_data

    start = pd.Timestamp.now(tz="Asia/Kolkata").normalize() - pd.Timedelta(days=120)
    accept = lambda trades: None
    for ticker, side, quantity, price, days_later in (
        ("DEMO-ALPHA.NS", "buy", 10, 1200.0, 0),
        ("DEMO-GAMMA.NS", "buy", 4, 3000.0, 10),
        ("DEMO-ALPHA.NS", "sell", 3, 1260.0, 60),
    ):
        trade_date = (start + pd.Timedelta(days=days_later)).date().isoformat()
        user_data.add_trade(
            {
                "ticker": ticker,
                "side": side,
                "quantity": quantity,
                "price": price,
                "trade_date": trade_date,
            },
            accept,
        )
    alerts.add_alert("DEMO-ALPHA.NS", "close_above", 100.0)
    alerts.add_alert("DEMO-BETA.NS", "move_at_least", 1.0)


def activate():
    """Set up the demo once per process. Streamlit reruns the page on every click."""
    global _active
    if _active:
        return

    # This comes first: importing api would otherwise load .env.
    os.environ["MARKETPULSE_DEMO"] = "1"
    for name in SECRET_NAMES:
        os.environ.pop(name, None)

    from fastapi.testclient import TestClient

    import api
    import dashboard_support
    import database
    from market_data import sample, service

    database.DATA_FOLDER = Path(tempfile.mkdtemp(prefix="marketpulse-demo-"))
    database.default_watchlist = lambda: [
        {"ticker": ticker, "is_fno": instrument.is_fno}
        for ticker, instrument in sample.INSTRUMENTS.items()
    ]
    service.PROVIDERS = [sample.SampleProvider()]

    dashboard_support.client = TestClient(api.app, raise_server_exceptions=False)
    dashboard_support.DEMO_NOTICE = NOTICE

    seed_sample_portfolio()
    _active = True

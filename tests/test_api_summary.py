"""Tests for GET /summary. These never touch the network.

All prices below are SYNTHETIC TEST DATA, not real market values. The database goes
to a temporary folder, set up in conftest.py.
"""

import pandas as pd
import pytest
from fastapi.testclient import TestClient

import api
import fetch_prices
import user_data
from market_data import service

NOW = pd.Timestamp("2026-10-30 19:00", tz="Asia/Kolkata")
DURING_SESSION = pd.Timestamp("2026-10-30 11:00", tz="Asia/Kolkata")

client = TestClient(api.app)


def make_history(bars=30):
    close = pd.Series([100.0 + i for i in range(bars)])
    history = pd.DataFrame(
        {
            "Open": close,
            "High": close + 1,
            "Low": close - 1,
            "Close": close,
            "Adj Close": close,
            "Volume": 1000,
        }
    )
    return history.set_index(
        pd.date_range(end="2026-10-30", periods=bars, freq="D", tz="Asia/Kolkata")
    )


class FakeProvider:
    name = "Fake provider"

    def __init__(self, broken=()):
        self.broken = broken

    def fetch_daily(self, ticker, period):
        if ticker in self.broken:
            raise ConnectionError("simulated outage")
        return make_history()


@pytest.fixture
def market(monkeypatch):
    def install(provider, now=NOW):
        monkeypatch.setattr(service, "PROVIDERS", [provider])
        monkeypatch.setattr(fetch_prices.pd.Timestamp, "now", lambda tz=None: now)

    return install


def test_summary_covers_the_watchlist_in_order(market):
    market(FakeProvider())

    body = client.get("/summary").json()

    assert [stock["ticker"] for stock in body["stocks"]] == list(user_data.load_watchlist())
    assert body["complete"] is True


def test_summary_values_match_metrics(market):
    market(FakeProvider())

    stock = client.get("/summary").json()["stocks"][0]
    metrics = client.get(f"/stocks/{stock['ticker']}/metrics").json()

    assert stock["close"] == metrics["close"] == 129.0
    assert stock["change_1d"] == metrics["change_1d"]
    assert stock["rsi_14"] == metrics["rsi_14"]
    assert stock["last_bar"] == "2026-10-30"
    assert stock["source"] == "Fake provider"


def test_summary_text_has_exact_values_source_and_disclaimer(market):
    market(FakeProvider())

    lines = client.get("/summary").json()["text"].splitlines()

    assert lines[0] == "MarketPulse summary, 2026-10-30 19:00 IST"
    # 128 to 129 is +0.78%, and a price that only rose has an RSI of 100.
    assert lines[1] == "RELIANCE.NS: 129.00 INR on 2026-10-30, 1D +0.78%, RSI 100.0"
    assert lines[-2] == "Source: Fake provider"
    assert lines[-1] == api.DISCLAIMER


def test_large_prices_use_thousands_separators():
    stock = api.StockSummary(
        ticker="TCS.NS", close=2502.6, last_bar="2026-10-30", change_1d=-0.0099, rsi_14=67.2
    )

    assert api.summary_line(stock) == "TCS.NS: 2,502.60 INR on 2026-10-30, 1D -0.99%, RSI 67.2"


def test_missing_indicators_are_shown_as_na_not_zero():
    stock = api.StockSummary(ticker="TCS.NS", close=100.0, last_bar="2026-10-30")

    assert api.summary_line(stock) == "TCS.NS: 100.00 INR on 2026-10-30, 1D n/a, RSI n/a"


def test_one_failed_stock_is_named_and_the_rest_still_arrive(market):
    market(FakeProvider(broken=["TCS.NS"]))

    response = client.get("/summary")
    body = response.json()
    stocks = {stock["ticker"]: stock for stock in body["stocks"]}

    assert response.status_code == 200
    assert body["complete"] is False
    assert stocks["TCS.NS"]["close"] is None
    assert "simulated outage" in stocks["TCS.NS"]["problem"]
    assert stocks["INFY.NS"]["close"] == 129.0
    assert "TCS.NS: unavailable (" in body["text"]


def test_a_total_outage_invents_nothing(market):
    tickers = list(user_data.load_watchlist())
    market(FakeProvider(broken=tickers))

    body = client.get("/summary").json()

    assert body["complete"] is False
    assert all(stock["close"] is None for stock in body["stocks"])
    assert "Source: none available" in body["text"]
    assert "INR" not in body["text"]


def test_summary_uses_finished_sessions_only(market):
    market(FakeProvider(), now=DURING_SESSION)

    stock = client.get("/summary").json()["stocks"][0]

    assert stock["last_bar"] == "2026-10-29"
    assert stock["close"] == 128.0
    assert stock["notes"] == ["left out today's unfinished bar (2026-10-30)"]


def test_summary_says_it_is_not_live(market):
    market(FakeProvider())

    body = client.get("/summary").json()

    assert body["data_type"] == "end_of_day"
    assert "not live" in body["disclaimer"]
    assert "not live" in body["text"]

"""Tests for api.py. These never touch the network.

All prices below are SYNTHETIC TEST DATA, not real market values.
"""

import pandas as pd
import pytest
from fastapi.testclient import TestClient

import api
import fetch_prices
from market_data import service

NOW = pd.Timestamp("2026-10-30 19:00", tz="Asia/Kolkata")
DURING_SESSION = pd.Timestamp("2026-10-30 11:00", tz="Asia/Kolkata")

client = TestClient(api.app)


def make_history(bars=30):
    """Valid synthetic daily bars ending on the same date as NOW."""
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


def with_placeholder(history, position):
    history = history.copy()
    previous_close = history["Close"].iloc[position - 1]
    for column in ["Open", "High", "Low", "Close", "Adj Close"]:
        history.iloc[position, history.columns.get_loc(column)] = previous_close
    history.iloc[position, history.columns.get_loc("Volume")] = 0
    return history


class FakeProvider:
    def __init__(self, name="Fake provider", table=None, error=None):
        self.name = name
        self.table = table
        self.error = error
        self.calls = []

    def fetch_daily(self, ticker, period):
        self.calls.append((ticker, period))
        if self.error:
            raise self.error
        return self.table


@pytest.fixture
def market(monkeypatch):
    """Return a function that installs fake providers and a fixed clock."""

    def install(*providers, now=NOW):
        monkeypatch.setattr(service, "PROVIDERS", list(providers))
        monkeypatch.setattr(fetch_prices.pd.Timestamp, "now", lambda tz=None: now)

    return install


def test_health_does_not_use_a_provider(market):
    provider = FakeProvider(error=AssertionError("should not be called"))
    market(provider)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert provider.calls == []


def test_stocks_are_listed_with_their_closing_time():
    stocks = client.get("/stocks").json()
    tcs = next(stock for stock in stocks if stock["ticker"] == "TCS.NS")
    assert len(stocks) == 4
    assert tcs == {
        "ticker": "TCS.NS",
        "nse_symbol": "TCS",
        "is_fno": True,
        "market_close": "15:35",
    }


@pytest.mark.parametrize("path", ["history", "metrics"])
def test_unknown_ticker_is_404_and_reaches_no_provider(market, path):
    provider = FakeProvider(error=AssertionError("should not be called"))
    market(provider)

    response = client.get(f"/stocks/NOPE.NS/{path}")

    assert response.status_code == 404
    assert provider.calls == []


def test_unsupported_period_is_rejected(market):
    provider = FakeProvider(table=make_history())
    market(provider)

    assert client.get("/stocks/TCS.NS/history?period=5y").status_code == 422
    assert provider.calls == []


def test_history_returns_bars_and_says_they_are_not_live(market):
    market(FakeProvider(table=make_history(3)))

    body = client.get("/stocks/TCS.NS/history").json()

    assert body["source"] == "Fake provider"
    assert body["data_type"] == "end_of_day"
    assert "not live" in body["disclaimer"]
    assert body["latest_bar_status"] == "complete daily bar"
    assert body["bars"][0] == {
        "date": "2026-10-28",
        "open": 100.0,
        "high": 101.0,
        "low": 99.0,
        "close": 100.0,
        "adj_close": 100.0,
        "volume": 1000,
    }


def test_history_passes_the_period_to_the_provider(market):
    provider = FakeProvider(table=make_history())
    market(provider)

    client.get("/stocks/TCS.NS/history?period=1y")

    assert provider.calls == [("TCS.NS", "1y")]


def test_history_removes_float_noise_from_prices(market):
    history = make_history(3)
    history.iloc[2, history.columns.get_loc("Close")] = 102.300049
    market(FakeProvider(table=history))

    assert client.get("/stocks/TCS.NS/history").json()["bars"][2]["close"] == 102.3


def test_history_removes_placeholders_and_says_so(market):
    market(FakeProvider(table=with_placeholder(make_history(5), 2)))

    body = client.get("/stocks/TCS.NS/history").json()

    assert len(body["bars"]) == 4
    assert "2026-10-28" not in [bar["date"] for bar in body["bars"]]
    assert body["notes"] == ["removed 1 zero-volume placeholder bar(s): 2026-10-28"]


def test_history_marks_todays_unfinished_bar(market):
    market(FakeProvider(table=make_history(3)), now=DURING_SESSION)

    body = client.get("/stocks/TCS.NS/history").json()

    assert len(body["bars"]) == 3
    assert "IN PROGRESS" in body["latest_bar_status"]
    assert body["latest_bar_in_progress"] is True


def test_history_marks_a_finished_bar(market):
    market(FakeProvider(table=make_history(3)))

    assert client.get("/stocks/TCS.NS/history").json()["latest_bar_in_progress"] is False


def test_history_from_a_source_without_adj_close_gives_null(market):
    market(FakeProvider(table=make_history(3).drop(columns="Adj Close")))

    body = client.get("/stocks/TCS.NS/history").json()

    assert body["bars"][0]["adj_close"] is None


def test_fallback_is_named_and_explained(market):
    down = FakeProvider("First", error=ConnectionError("simulated outage"))
    market(down, FakeProvider("Second", table=make_history(3)))

    body = client.get("/stocks/TCS.NS/history").json()

    assert body["source"] == "Second"
    assert "simulated outage" in body["notes"][0]


@pytest.mark.parametrize("path", ["history", "metrics"])
def test_no_usable_data_is_503_with_the_reasons(market, path):
    market(FakeProvider("First", error=ConnectionError("simulated outage")))

    response = client.get(f"/stocks/TCS.NS/{path}")

    assert response.status_code == 503
    detail = response.json()["detail"]
    assert detail["message"] == "No usable data for TCS.NS"
    assert "simulated outage" in detail["failures"][0]


def test_only_placeholder_bars_is_503(market):
    history = make_history(2)
    history = with_placeholder(history, 1)
    history = history.iloc[[1]]
    market(FakeProvider(table=history))

    assert client.get("/stocks/TCS.NS/history").status_code == 503


def test_history_refuses_data_that_fails_validation(market):
    history = make_history(3)
    history.iloc[1, history.columns.get_loc("Close")] = -5.0
    market(FakeProvider(table=history))

    response = client.get("/stocks/TCS.NS/history")

    assert response.status_code == 503
    assert "negative prices" in response.json()["detail"]["failures"][0]


def test_every_metric_comes_from_its_own_summary_value(market, monkeypatch):
    # Each value is different, so a field wired to the wrong metric cannot pass.
    labels = {
        "Close": "close",
        "1D change": "change_1d",
        "Price return": "price_return",
        "Total return": "total_return",
        "Volatility (ann.)": "volatility_annualised",
        "Max drawdown": "max_drawdown",
        "52W high": "high_52w",
        "52W low": "low_52w",
        "SMA 20": "sma_20",
        "SMA 50": "sma_50",
        "SMA 200": "sma_200",
        "EMA 20": "ema_20",
        "RSI 14": "rsi_14",
    }
    summary = {label: float(number) for number, label in enumerate(labels, start=1)}
    summary.update(
        {
            "Bars used": 30,
            "First bar": pd.Timestamp("2026-10-01"),
            "Last bar": pd.Timestamp("2026-10-30"),
        }
    )
    monkeypatch.setattr(api.analytics, "summarize", lambda history: summary)
    market(FakeProvider(table=make_history()))

    body = client.get("/stocks/TCS.NS/metrics").json()

    assert {field: body[field] for field in labels.values()} == {
        field: float(number) for number, field in enumerate(labels.values(), start=1)
    }


def test_metrics_values(market):
    market(FakeProvider(table=make_history(30)))

    body = client.get("/stocks/TCS.NS/metrics").json()

    assert body["bars_used"] == 30
    assert body["first_bar"] == "2026-10-01"
    assert body["last_bar"] == "2026-10-30"
    assert body["close"] == 129.0
    assert body["price_return"] == pytest.approx(0.29)  # 100 to 129
    assert body["total_return"] == pytest.approx(0.29)
    assert body["change_1d"] == pytest.approx(1 / 128, abs=1e-6)
    assert body["max_drawdown"] == 0
    assert body["high_52w"] == 130.0
    assert body["low_52w"] == 99.0
    assert body["sma_20"] == 119.5  # mean of 110 to 129
    assert body["rsi_14"] == 100


def test_metrics_too_short_for_an_indicator_are_null_not_an_error(market):
    market(FakeProvider(table=make_history(30)))

    response = client.get("/stocks/TCS.NS/metrics")

    assert response.status_code == 200
    assert response.json()["sma_50"] is None
    assert response.json()["sma_200"] is None


def test_metrics_leave_out_todays_unfinished_bar(market):
    market(FakeProvider(table=make_history(30)), now=DURING_SESSION)

    body = client.get("/stocks/TCS.NS/metrics").json()

    assert body["bars_used"] == 29
    assert body["last_bar"] == "2026-10-29"
    assert body["notes"] == ["left out today's unfinished bar (2026-10-30)"]


def test_metrics_request_a_full_year(market):
    provider = FakeProvider(table=make_history())
    market(provider)

    client.get("/stocks/TCS.NS/metrics")

    assert provider.calls == [("TCS.NS", "1y")]


def test_metrics_refuse_a_source_without_adj_close(market):
    market(FakeProvider(table=make_history().drop(columns="Adj Close")))

    response = client.get("/stocks/TCS.NS/metrics")

    assert response.status_code == 503
    assert "Adj Close" in response.json()["detail"]["failures"][0]


def test_metrics_with_only_an_unfinished_bar_is_503(market):
    market(FakeProvider(table=make_history(1)), now=DURING_SESSION)

    assert client.get("/stocks/TCS.NS/metrics").status_code == 503

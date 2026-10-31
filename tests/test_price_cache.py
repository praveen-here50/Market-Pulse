"""Tests for price_cache.py and how the API uses it. These never touch the network.

All prices below are SYNTHETIC TEST DATA, not real market values. The database goes
to a temporary folder, set up in conftest.py.
"""

from contextlib import closing
from datetime import time

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

import api
import database
import fetch_prices
import price_cache
from market_data import service

IST = "Asia/Kolkata"
FNO_CLOSE = time(15, 35)
NON_FNO_CLOSE = time(15, 30)

client = TestClient(api.app)


def at(text):
    return pd.Timestamp(f"2026-10-30 {text}", tz=IST)


def make_history(last_close=1000.0, bars=5, end="2026-10-30"):
    close = pd.Series([last_close - bars + 1 + i for i in range(bars)])
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
    return history.set_index(pd.date_range(end=end, periods=bars, freq="D", tz=IST))


class FakeProvider:
    def __init__(self, table=None, error=None, name="Fake provider", splits=None):
        self.name = name
        self.table = make_history() if table is None else table
        self.error = error
        self.splits = splits or {}
        self.calls = []
        self.split_requests = 0

    def fetch_daily(self, ticker, period):
        self.calls.append((ticker, period))
        if self.error:
            raise self.error
        return self.table

    def fetch_splits(self, ticker, since):
        self.split_requests += 1
        return self.splits


@pytest.fixture
def market(monkeypatch):
    def install(*providers, now=at("19:00")):
        monkeypatch.setattr(service, "PROVIDERS", list(providers))
        monkeypatch.setattr(fetch_prices.pd.Timestamp, "now", lambda tz=None: now)

    return install


def accept(table):
    return []


@pytest.mark.parametrize(
    "downloaded, read, market_close, usable",
    [
        ("19:00", "19:00", FNO_CLOSE, True),
        ("19:00", "19:14", FNO_CLOSE, True),
        ("19:00", "19:15", FNO_CLOSE, False),
        ("19:00", "18:59", FNO_CLOSE, False),
        # During the session, a copy may be reused within MAX_AGE.
        ("11:00", "11:10", FNO_CLOSE, True),
        # Downloaded before the close and read after it: the bar was not final.
        ("15:30", "15:36", FNO_CLOSE, False),
        ("15:34", "15:35", FNO_CLOSE, False),
        ("15:28", "15:31", NON_FNO_CLOSE, False),
        # The same read is still before the close for an F&O stock.
        ("15:28", "15:31", FNO_CLOSE, True),
        # Downloaded at or after the close, the bar was already final.
        ("15:35", "15:45", FNO_CLOSE, True),
        ("15:36", "15:40", FNO_CLOSE, True),
    ],
)
def test_is_usable(downloaded, read, market_close, usable):
    assert price_cache.is_usable(at(downloaded), at(read), market_close) is usable


def test_a_copy_from_yesterday_evening_is_not_usable_this_morning():
    yesterday = pd.Timestamp("2026-10-29 23:59", tz=IST)
    assert price_cache.is_usable(yesterday, at("00:05"), FNO_CLOSE) is True
    assert price_cache.is_usable(yesterday, at("09:15"), FNO_CLOSE) is False


def test_saved_bars_come_back_exactly():
    table = make_history()
    # Yahoo's real prices have long decimals. None may be rounded on the way.
    table.loc[table.index[0], "Close"] = 1204.300048828125
    table.loc[table.index[1], "Adj Close"] = np.nan
    table["Dividends"] = 0.0

    price_cache.save("TCS.NS", "1mo", table, "Fake provider", at("19:00"))
    saved = price_cache.load("TCS.NS", "1mo", at("19:01"), FNO_CLOSE)

    expected = table.drop(columns="Dividends")
    pd.testing.assert_frame_equal(saved.history, expected, check_freq=False, check_index_type=False, check_names=False)
    assert saved.source == "Fake provider"
    assert saved.downloaded_at == at("19:00")
    assert str(saved.history.index.tz) == IST


def test_a_table_without_adj_close_can_be_saved():
    table = make_history().drop(columns="Adj Close")

    price_cache.save("TCS.NS", "1mo", table, "Fake provider", at("19:00"))
    saved = price_cache.load("TCS.NS", "1mo", at("19:01"), FNO_CLOSE)

    assert saved.history["Adj Close"].isna().all()


def test_saving_again_replaces_the_old_bars():
    price_cache.save("TCS.NS", "1mo", make_history(bars=10), "Fake provider", at("19:00"))
    price_cache.save("TCS.NS", "1mo", make_history(bars=3), "Fake provider", at("19:05"))

    saved = price_cache.load("TCS.NS", "1mo", at("19:06"), FNO_CLOSE)

    assert len(saved.history) == 3
    with closing(database.connect()) as connection:
        assert connection.execute("SELECT COUNT(*) FROM price_bars").fetchone()[0] == 3


def test_second_request_is_answered_from_the_saved_copy_and_says_so(market):
    provider = FakeProvider()
    market(provider, now=at("19:00"))
    first = client.get("/stocks/TCS.NS/history").json()

    market(provider, now=at("19:10"))
    second = client.get("/stocks/TCS.NS/history").json()

    assert provider.calls == [("TCS.NS", "1mo")]
    assert first["notes"] == []
    assert second["notes"] == ["saved copy, downloaded 2026-10-30 19:00 IST"]
    assert second["source"] == first["source"]
    assert second["bars"] == first["bars"]
    assert second["disclaimer"] == first["disclaimer"]


def test_an_old_copy_is_downloaded_again(market):
    provider = FakeProvider()
    market(provider, now=at("19:00"))
    client.get("/stocks/TCS.NS/history")

    market(provider, now=at("19:15"))
    response = client.get("/stocks/TCS.NS/history").json()

    assert len(provider.calls) == 2
    assert response["notes"] == []


def test_each_stock_and_period_has_its_own_copy(market):
    provider = FakeProvider()
    market(provider)

    client.get("/stocks/TCS.NS/history?period=1mo")
    client.get("/stocks/TCS.NS/history?period=1y")
    client.get("/stocks/INFY.NS/history?period=1mo")

    assert len(provider.calls) == 3


def test_metrics_share_the_one_year_copy_with_history(market):
    provider = FakeProvider(make_history(bars=30))
    market(provider)

    client.get("/stocks/TCS.NS/history?period=1y")
    response = client.get("/stocks/TCS.NS/metrics")

    assert response.status_code == 200
    assert len(provider.calls) == 1


def test_a_bar_saved_during_the_session_is_not_shown_as_finished(market):
    """TCS is an F&O stock, so its session closes at 15:35."""
    provider = FakeProvider(make_history(last_close=1000.0))
    market(provider, now=at("15:30"))
    client.get("/stocks/TCS.NS/history")

    provider.table = make_history(last_close=1050.0)
    market(provider, now=at("15:36"))
    response = client.get("/stocks/TCS.NS/history").json()

    assert response["latest_bar_in_progress"] is False
    assert response["bars"][-1]["close"] == 1050.0


def test_portfolio_does_not_value_at_a_bar_saved_during_the_session(market):
    provider = FakeProvider(make_history(last_close=1000.0))
    market(provider, now=at("15:30"))
    client.post(
        "/trades",
        json={"ticker": "TCS.NS", "side": "buy", "quantity": 10, "price": 800.0, "trade_date": "2026-01-10"},
    )
    during = client.get("/portfolio").json()["holdings"][0]

    provider.table = make_history(last_close=1050.0)
    market(provider, now=at("15:36"))
    after = client.get("/portfolio").json()["holdings"][0]

    # During the session the last finished close is the previous day's bar.
    assert during["last_close"] == 999.0
    assert after["last_close"] == 1050.0
    assert after["market_value"] == 10500.0


def test_a_fallback_answer_is_not_saved(market):
    down = FakeProvider(error=ConnectionError("simulated outage"), name="Primary")
    backup = FakeProvider(name="Backup")
    market(down, backup, now=at("19:00"))
    assert client.get("/stocks/TCS.NS/history").json()["source"] == "Backup"

    recovered = FakeProvider(name="Primary")
    market(recovered, backup, now=at("19:01"))

    assert client.get("/stocks/TCS.NS/history").json()["source"] == "Primary"


def test_an_outage_gives_an_error_not_an_old_copy(market):
    provider = FakeProvider()
    market(provider, now=at("19:00"))
    client.get("/stocks/TCS.NS/history")

    provider.error = ConnectionError("simulated outage")
    market(provider, now=at("19:15"))

    assert client.get("/stocks/TCS.NS/history").status_code == 503


def test_a_copy_that_fails_the_check_is_not_used(market):
    no_adj_close = make_history(bars=30).drop(columns="Adj Close")
    provider = FakeProvider(no_adj_close)
    market(provider)
    assert client.get("/stocks/TCS.NS/history?period=1y").status_code == 200

    # /metrics needs Adj Close, so it must ask the provider instead.
    provider.table = make_history(bars=30)
    response = client.get("/stocks/TCS.NS/metrics")

    assert response.status_code == 200
    assert len(provider.calls) == 2


def test_placeholder_bars_are_still_removed_from_a_saved_copy(market):
    table = make_history()
    day = table.index[2]
    table.loc[day, ["Open", "High", "Low", "Close", "Adj Close"]] = table["Close"].iloc[1]
    table.loc[day, "Volume"] = 0
    market(FakeProvider(table))

    client.get("/stocks/TCS.NS/history")
    response = client.get("/stocks/TCS.NS/history").json()

    assert len(response["bars"]) == 4
    assert response["notes"][0].startswith("saved copy")
    assert "removed 1 zero-volume placeholder" in response["notes"][1]


def test_adding_a_stock_always_asks_a_provider(market):
    provider = FakeProvider()
    market(provider)

    client.post("/stocks", json={"ticker": "IRCTC.NS", "is_fno": False})
    client.delete("/stocks/IRCTC.NS")
    client.post("/stocks", json={"ticker": "IRCTC.NS", "is_fno": False})

    assert len(provider.calls) == 2


def buy_ten():
    response = client.post(
        "/trades",
        json={"ticker": "TCS.NS", "side": "buy", "quantity": 10, "price": 800.0, "trade_date": "2026-01-10"},
    )
    assert response.status_code == 201


def test_splits_are_asked_for_every_time(market):
    provider = FakeProvider()
    market(provider)
    buy_ten()

    client.get("/portfolio")
    client.get("/portfolio")

    assert provider.split_requests == 2
    assert len(provider.calls) == 1


def test_a_new_split_never_meets_prices_from_before_it(market):
    """10 shares at a close of 1000 become 20 at 500. Their value must stay 10000."""
    provider = FakeProvider(make_history(last_close=1000.0))
    market(provider, now=at("10:00"))
    buy_ten()
    assert client.get("/portfolio").json()["holdings"][0]["market_value"] == 9990.0

    provider.splits = {"2026-10-30": 2.0}
    provider.table = make_history(last_close=500.0)
    market(provider, now=at("10:05"))
    holding = client.get("/portfolio").json()["holdings"][0]

    assert holding["quantity"] == 20
    assert holding["last_close"] == 499.0
    assert holding["market_value"] == 9980.0


def test_an_old_split_does_not_stop_the_cache(market):
    provider = FakeProvider(splits={"2026-02-01": 2.0})
    market(provider)
    buy_ten()

    client.get("/portfolio")
    client.get("/portfolio")

    assert len(provider.calls) == 1

"""Tests for the watchlist and portfolio endpoints. These never touch the network.

All prices below are SYNTHETIC TEST DATA, not real market values. Files go to a
temporary folder, set up in conftest.py.
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


def make_history(last_close=1000.0, bars=5):
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
    return history.set_index(
        pd.date_range(end="2026-10-30", periods=bars, freq="D", tz="Asia/Kolkata")
    )


class FakeProvider:
    name = "Fake provider"

    def __init__(self, table=None, splits=None, table_error=None, splits_error=None):
        self.table = make_history() if table is None else table
        self.splits = splits or {}
        self.table_error = table_error
        self.splits_error = splits_error
        self.split_requests = []

    def fetch_daily(self, ticker, period):
        if self.table_error:
            raise self.table_error
        return self.table

    def fetch_splits(self, ticker, since):
        self.split_requests.append((ticker, since))
        if self.splits_error:
            raise self.splits_error
        return self.splits


@pytest.fixture
def market(monkeypatch):
    def install(provider=None, now=NOW):
        provider = provider or FakeProvider()
        monkeypatch.setattr(service, "PROVIDERS", [provider])
        monkeypatch.setattr(fetch_prices.pd.Timestamp, "now", lambda tz=None: now)
        return provider

    install()
    return install


def buy(quantity=10, price=800.0, date="2026-01-10", ticker="TCS.NS"):
    return client.post(
        "/trades",
        json={"ticker": ticker, "side": "buy", "quantity": quantity, "price": price, "trade_date": date},
    )


def sell(quantity=5, price=900.0, date="2026-02-10", ticker="TCS.NS"):
    return client.post(
        "/trades",
        json={"ticker": ticker, "side": "sell", "quantity": quantity, "price": price, "trade_date": date},
    )


def test_adding_a_stock_shows_it_in_stocks(market):
    response = client.post("/stocks", json={"ticker": "IRCTC.NS", "is_fno": False})

    assert response.status_code == 201
    stocks = {stock["ticker"]: stock for stock in client.get("/stocks").json()}
    assert stocks["IRCTC.NS"]["market_close"] == "15:30"


def test_added_stock_works_everywhere(market):
    client.post("/stocks", json={"ticker": "M&M.NS", "is_fno": True})

    assert client.get("/stocks/M&M.NS/history").status_code == 200
    assert client.get("/stocks/M&M.NS/metrics").status_code == 200


def test_non_fno_stock_uses_its_own_close_for_the_unfinished_bar(market):
    client.post("/stocks", json={"ticker": "IRCTC.NS", "is_fno": False})
    client.post("/stocks", json={"ticker": "ABB.NS", "is_fno": True})
    market(now=pd.Timestamp("2026-10-30 15:32", tz="Asia/Kolkata"))

    assert client.get("/stocks/IRCTC.NS/history").json()["latest_bar_in_progress"] is False
    assert client.get("/stocks/ABB.NS/history").json()["latest_bar_in_progress"] is True


@pytest.mark.parametrize("ticker", ["TCS", "tcs.ns", "TCS.BO", "../TCS.NS", ""])
def test_badly_formed_tickers_are_refused(market, ticker):
    assert client.post("/stocks", json={"ticker": ticker, "is_fno": True}).status_code == 422


def test_stock_without_valid_data_is_not_added(market):
    market(FakeProvider(table=pd.DataFrame()))

    response = client.post("/stocks", json={"ticker": "NOSUCH.NS", "is_fno": False})

    assert response.status_code == 422
    assert "No valid data" in response.json()["detail"]
    assert "NOSUCH.NS" not in user_data.load_watchlist()


def test_duplicate_stock_is_a_conflict(market):
    response = client.post("/stocks", json={"ticker": "TCS.NS", "is_fno": True})
    assert response.status_code == 409


def test_removing_a_stock(market):
    assert client.delete("/stocks/TCS.NS").status_code == 204
    assert client.get("/stocks/TCS.NS/history").status_code == 404


def test_removing_an_unknown_stock_is_404(market):
    assert client.delete("/stocks/NOPE.NS").status_code == 404


def test_removing_a_stock_with_trades_is_a_conflict(market):
    buy()

    response = client.delete("/stocks/TCS.NS")

    assert response.status_code == 409
    assert "has trades" in response.json()["detail"]


def test_empty_portfolio(market):
    body = client.get("/portfolio").json()
    assert body["holdings"] == []
    assert body["total_market_value"] == 0
    assert "not your real returns" in body["disclaimer"]


def test_holding_is_valued_at_the_last_close(market):
    # 10 at 800 cost 8,000. 10 at the 1,000 close is 10,000, a gain of 2,000 or 25%.
    buy()

    body = client.get("/portfolio").json()

    holding = body["holdings"][0]
    assert holding["quantity"] == 10
    assert holding["average_cost"] == 800
    assert holding["invested"] == 8000
    assert holding["last_close"] == 1000
    assert holding["last_close_date"] == "2026-10-30"
    assert holding["source"] == "Fake provider"
    assert holding["market_value"] == 10000
    assert holding["unrealised"] == 2000
    assert holding["unrealised_fraction"] == 0.25
    assert body["total_market_value"] == 10000


def test_a_split_after_buying_does_not_look_like_a_crash(market):
    # Bought 100 at 1,600, then 2-for-1. The adjusted close is 800, so the value
    # is 200 * 800 = 160,000: no loss. Ignoring the split would show -50%.
    market(FakeProvider(table=make_history(800.0), splits={"2026-02-01": 2.0}))
    buy(quantity=100, price=1600.0)

    holding = client.get("/portfolio").json()["holdings"][0]

    assert holding["quantity"] == 200
    assert holding["average_cost"] == 800
    assert holding["market_value"] == 160000
    assert holding["unrealised"] == 0


def test_totals_add_up_across_stocks(market):
    buy(quantity=10, price=800.0)
    buy(quantity=5, price=1200.0, ticker="INFY.NS")

    body = client.get("/portfolio").json()

    assert body["total_invested"] == 14000  # 8,000 + 6,000
    assert body["total_market_value"] == 15000  # 10,000 + 5,000
    assert body["total_unrealised"] == 1000  # +2,000 and -1,000


def test_realised_profit_stays_after_selling_everything(market):
    # Bought 10 at 800, sold 10 at 900: 1,000 realised, nothing left to value.
    market(FakeProvider(table_error=ConnectionError("should not be needed")))
    buy()
    sell(quantity=10)

    body = client.get("/portfolio").json()

    assert body["holdings"][0]["quantity"] == 0
    assert body["holdings"][0]["realised"] == 1000
    assert body["total_market_value"] == 0


def test_unfinished_session_is_not_used_for_valuing(market):
    market(now=DURING_SESSION)
    buy()

    holding = client.get("/portfolio").json()["holdings"][0]

    assert holding["last_close_date"] == "2026-10-29"
    assert holding["last_close"] == 999


def test_missing_price_makes_the_total_unknown_not_smaller(market):
    buy()
    market(FakeProvider(table_error=ConnectionError("simulated outage")))

    body = client.get("/portfolio").json()

    assert body["holdings"][0]["market_value"] is None
    assert "simulated outage" in body["holdings"][0]["problem"]
    assert body["total_market_value"] is None
    assert body["total_unrealised"] is None


def test_missing_splits_give_nulls_and_not_an_unadjusted_quantity(market):
    buy()
    market(FakeProvider(splits_error=ConnectionError("simulated outage")))

    response = client.get("/portfolio")

    assert response.status_code == 200
    holding = response.json()["holdings"][0]
    assert holding["quantity"] is None
    assert "simulated outage" in holding["problem"]
    assert response.json()["total_invested"] is None


def test_one_failed_stock_does_not_hide_the_others(market, monkeypatch):
    provider = market()
    buy()
    buy(ticker="INFY.NS")
    real_fetch = provider.fetch_splits

    def fail_for_tcs(ticker, since):
        if ticker == "TCS.NS":
            raise ConnectionError("simulated outage")
        return real_fetch(ticker, since)

    monkeypatch.setattr(provider, "fetch_splits", fail_for_tcs)

    holdings = {item["ticker"]: item for item in client.get("/portfolio").json()["holdings"]}

    assert holdings["TCS.NS"]["market_value"] is None
    assert holdings["INFY.NS"]["market_value"] == 10000


def test_splits_are_requested_from_before_the_first_trade(market):
    provider = market()
    buy(date="2026-01-10")
    buy(date="2025-06-15")

    client.get("/portfolio")

    assert provider.split_requests == [("TCS.NS", "2025-06-05")]


def test_buying_needs_no_download(market):
    provider = market(FakeProvider(splits_error=AssertionError("should not be called")))

    assert buy().status_code == 201
    assert provider.split_requests == []


def test_trade_for_a_stock_not_on_the_watchlist_is_404(market):
    assert buy(ticker="NOPE.NS").status_code == 404


def test_future_trade_is_refused(market):
    assert buy(date="2026-10-31").status_code == 422


@pytest.mark.parametrize(
    ("field", "value"), [("quantity", 0), ("quantity", -1), ("quantity", 1.5), ("price", 0), ("side", "hold")]
)
def test_invalid_trade_values_are_refused(market, field, value):
    trade = {"ticker": "TCS.NS", "side": "buy", "quantity": 1, "price": 1.0, "trade_date": "2026-01-01"}

    assert client.post("/trades", json={**trade, field: value}).status_code == 422
    assert user_data.load_trades() == []


def test_selling_more_than_held_is_a_conflict_and_is_not_saved(market):
    buy(quantity=10)

    response = sell(quantity=11)

    assert response.status_code == 409
    assert "only 10 held" in response.json()["detail"]
    assert len(user_data.load_trades()) == 1


def test_selling_bonus_shares_is_allowed(market):
    market(FakeProvider(splits={"2026-02-01": 2.0}))
    buy(quantity=10)

    assert sell(quantity=15).status_code == 201


def test_sale_is_refused_when_split_history_is_unavailable(market):
    buy()
    market(FakeProvider(splits_error=ConnectionError("simulated outage")))

    assert sell().status_code == 503
    assert len(user_data.load_trades()) == 1


def test_trades_are_listed_oldest_first(market):
    buy(date="2026-03-01")
    buy(date="2026-01-01")

    dates = [trade["trade_date"] for trade in client.get("/trades").json()]

    assert dates == ["2026-01-01", "2026-03-01"]


def test_deleting_a_trade_corrects_the_holding(market):
    buy(quantity=10)
    mistake = buy(quantity=99).json()

    assert client.delete(f"/trades/{mistake['id']}").status_code == 204
    assert client.get("/portfolio").json()["holdings"][0]["quantity"] == 10


def test_deleting_a_buy_that_a_sale_needs_is_a_conflict(market):
    bought = buy(quantity=10).json()
    sell(quantity=5)

    assert client.delete(f"/trades/{bought['id']}").status_code == 409
    assert len(user_data.load_trades()) == 2


def test_deleting_an_unknown_trade_is_404(market):
    assert client.delete("/trades/nope").status_code == 404

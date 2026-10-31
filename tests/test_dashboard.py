"""Tests that run dashboard.py headless. These never touch the network.

All values below are SYNTHETIC TEST DATA, not real market values.
"""

from pathlib import Path

import pandas as pd
import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

import dashboard_support as support

DASHBOARD_FILE = Path(__file__).parent.parent / "dashboard.py"

STOCKS = [
    {"ticker": "TCS.NS", "nse_symbol": "TCS", "is_fno": True, "market_close": "15:35"},
    {"ticker": "INFY.NS", "nse_symbol": "INFY", "is_fno": True, "market_close": "15:35"},
]


def make_history(in_progress=False, notes=()):
    dates = pd.date_range(end="2026-10-30", periods=260, freq="D")
    closes = [100.0 + i for i in range(260)]
    return {
        "ticker": "TCS.NS",
        "source": "Fake provider",
        "data_type": "end_of_day",
        "disclaimer": "not live",
        "notes": list(notes),
        "latest_bar_status": "complete daily bar",
        "latest_bar_in_progress": in_progress,
        "bars": [
            {
                "date": f"{day:%Y-%m-%d}",
                "open": close,
                "high": close + 1,
                "low": close - 1,
                "close": close,
                "adj_close": close,
                "volume": 1000,
            }
            for day, close in zip(dates, closes)
        ],
    }


def make_metrics():
    metrics = {field: 0.25 for field in support.COMPARISON_ROWS}
    metrics |= {"close": 2502.6, "rsi_14": None, "ticker": "TCS.NS"}
    return metrics


EMPTY_PORTFOLIO = {
    "data_type": "end_of_day",
    "disclaimer": "Valued at the last close, not a live price. Leaves out brokerage.",
    "holdings": [],
    "total_invested": 0,
    "total_market_value": 0,
    "total_unrealised": 0,
    "total_realised": 0,
}


def make_holding(**changes):
    holding = {
        "ticker": "TCS.NS",
        "quantity": 10,
        "average_cost": 800.0,
        "invested": 8000.0,
        "last_close": 1000.0,
        "last_close_date": "2026-10-30",
        "source": "Fake provider",
        "market_value": 10000.0,
        "unrealised": 2000.0,
        "unrealised_fraction": 0.25,
        "realised": 0.0,
        "problem": None,
    }
    return holding | changes


def make_portfolio(*holdings, **totals):
    return EMPTY_PORTFOLIO | {
        "holdings": list(holdings),
        "total_invested": 8000.0,
        "total_market_value": 10000.0,
        "total_unrealised": 2000.0,
        "total_realised": 0.0,
    } | totals


TRADE = {
    "id": "abc",
    "ticker": "TCS.NS",
    "side": "buy",
    "quantity": 10,
    "price": 800.0,
    "trade_date": "2026-01-10",
}


OVERVIEW = {
    "advancers": 1,
    "decliners": 0,
    "unchanged": 0,
    "stocks": [
        {
            "ticker": "TCS.NS",
            "last_bar": "2026-10-30",
            "close": 100.0,
            "change_1d": 0.01,
            "distance_from_52w_high": -0.05,
            "above_sma_200": None,
            "rsi_14": 55.0,
        }
    ],
    "unavailable": [{"ticker": "INFY.NS", "problem": "simulated outage"}],
}
NEWS = {
    "source": "Fake provider",
    "disclaimer": "Not checked.",
    "articles": [
        {
            "title": "SYNTHETIC headline",
            "publisher": "Test Wire",
            "published_at": "2026-10-30T10:00:00Z",
            "link": "https://example.com/a",
        }
    ],
}
ALERT = {
    "id": "a1",
    "ticker": "TCS.NS",
    "kind": "close_above",
    "threshold": 2500.0,
    "was_met": True,
    "last_checked_bar": "2026-10-30",
}


def serve(
    monkeypatch,
    *,
    stocks=STOCKS,
    history=None,
    metrics=None,
    portfolio=None,
    trades=(),
    overview=OVERVIEW,
    news=NEWS,
    alerts=(),
):
    """Replace the API. An exception given for a value is raised instead of returned."""

    def answer(value):
        if isinstance(value, Exception):
            raise value
        return value

    def fake_fetch(path):
        if path == "/stocks":
            return answer(stocks)
        if path == "/portfolio":
            return answer(EMPTY_PORTFOLIO if portfolio is None else portfolio)
        if path == "/trades":
            return list(trades)
        if path == "/analytics":
            return answer(overview)
        if path == "/alerts":
            return list(alerts)
        if path.endswith("/news"):
            return answer(news)
        if path.endswith("/metrics"):
            return answer(make_metrics() if metrics is None else metrics)
        return answer(make_history() if history is None else history)

    monkeypatch.setattr(support, "fetch_json", fake_fetch)


@pytest.fixture(autouse=True)
def clear_cache():
    st.cache_data.clear()


def run_page():
    return AppTest.from_file(str(DASHBOARD_FILE), default_timeout=30).run()


def all_text(page):
    parts = [element.value for group in (page.caption, page.warning, page.error, page.info) for element in group]
    return " ".join(parts)


def tile_values(page):
    return {metric.label: metric.value for metric in page.metric}


def test_page_says_data_is_not_live_and_names_the_source(monkeypatch):
    serve(monkeypatch)

    page = run_page()

    assert not page.exception
    assert "not live exchange prices" in page.info[0].value
    assert "not predictions" in page.info[0].value
    assert "Source: Fake provider" in all_text(page)
    assert "Last bar: 2026-10-30" in all_text(page)


def test_tiles_show_values_and_unknown_values_as_na(monkeypatch):
    serve(monkeypatch)

    tiles = tile_values(run_page())

    assert tiles["Close"] == "₹2,502.60"
    assert tiles["Total return (1Y)"] == "+25.00%"
    assert tiles["RSI 14"] == "n/a"


def test_tiles_are_not_colored_as_good_or_bad(monkeypatch):
    serve(monkeypatch)
    assert all(not metric.delta for metric in run_page().metric)


def test_every_stock_can_be_chosen(monkeypatch):
    serve(monkeypatch)
    assert run_page().selectbox[0].options == ["TCS.NS", "INFY.NS"]


def test_changing_the_view_reruns_without_error(monkeypatch):
    serve(monkeypatch)

    page = run_page()
    page.radio[0].set_value("1 month").run()

    assert not page.exception


def test_stopped_api_explains_how_to_start_it(monkeypatch):
    serve(monkeypatch, stocks=support.ApiNotRunning("refused"))

    page = run_page()

    assert not page.exception
    assert "API is not running" in page.error[0].value
    assert "uvicorn api:app" in page.code[0].value


def test_api_stopping_after_the_first_call_is_also_explained(monkeypatch):
    serve(monkeypatch, history=support.ApiNotRunning("refused"))

    page = run_page()

    assert "API is not running" in page.error[0].value


def test_missing_prices_are_explained_without_any_tiles(monkeypatch):
    down = support.DataUnavailable(["Yahoo: down"])
    serve(monkeypatch, history=down, metrics=down, overview=down)

    page = run_page()

    assert not page.exception
    assert "No usable price data for TCS.NS" in all_text(page)
    assert "Yahoo: down" in all_text(page)
    assert len(page.metric) == 0


def test_fallback_prices_still_show_when_metrics_are_refused(monkeypatch):
    # This is the real outage case: bhavcopy has prices but no Adj Close.
    history = make_history(notes=["fallback used because Yahoo: down"])
    refused = support.DataUnavailable(["no Adj Close"])
    serve(monkeypatch, history=history, metrics=refused, overview=refused)

    page = run_page()

    assert not page.exception
    assert "Metrics are unavailable" in all_text(page)
    assert "no Adj Close" in all_text(page)
    assert "fallback used because Yahoo: down" in all_text(page)
    assert len(page.metric) == 0


def test_unfinished_session_is_called_out(monkeypatch):
    serve(monkeypatch, history=make_history(in_progress=True))

    assert "has not closed" in all_text(run_page())


def test_finished_session_gets_no_warning(monkeypatch):
    serve(monkeypatch)
    assert "has not closed" not in all_text(run_page())


def record_changes(monkeypatch, error=None):
    """Replace send_json and return the list of changes the page tries to make."""
    sent = []

    def fake_send(method, path, body=None):
        sent.append((method, path, body))
        if error:
            raise error

    monkeypatch.setattr(support, "send_json", fake_send)
    return sent


def button(page, label):
    return next(item for item in page.button if item.label == label)


def test_portfolio_shows_totals_and_the_valuation_disclaimer(monkeypatch):
    serve(monkeypatch, portfolio=make_portfolio(make_holding()), trades=[TRADE])

    page = run_page()

    tiles = tile_values(page)
    assert not page.exception
    assert tiles["Market value"] == "₹10,000.00"
    assert tiles["Unrealised P&L"] == "+₹2,000.00"
    assert any("not a live price" in info.value for info in page.info)


def test_empty_portfolio_invites_a_first_trade(monkeypatch):
    serve(monkeypatch)

    page = run_page()

    assert not page.exception
    assert "Market value" not in tile_values(page)
    assert any("No trades recorded yet" in item.value for item in page.markdown)


def test_holding_that_cannot_be_valued_is_called_out(monkeypatch):
    unknown = make_holding(market_value=None, unrealised=None, problem="Yahoo: down")
    portfolio = make_portfolio(unknown, total_market_value=None, total_unrealised=None)
    serve(monkeypatch, portfolio=portfolio)

    page = run_page()

    assert tile_values(page)["Market value"] == "n/a"
    assert "TCS.NS could not be valued" in all_text(page)
    assert "Yahoo: down" in all_text(page)


def test_saving_a_trade_sends_it_to_the_api(monkeypatch):
    serve(monkeypatch)
    sent = record_changes(monkeypatch)

    page = run_page()
    next(item for item in page.number_input if item.label == "Price per share (₹)").set_value(812.5)
    next(item for item in page.number_input if item.label == "Quantity").set_value(3)
    button(page, "Save trade").click().run()

    method, path, body = sent[0]
    assert (method, path) == ("POST", "/trades")
    assert body["quantity"] == 3
    assert body["price"] == 812.5
    assert body["side"] == "buy"


def test_refused_sale_shows_the_reason(monkeypatch):
    serve(monkeypatch)
    record_changes(monkeypatch, support.RequestRejected("only 10 held then"))

    page = run_page()
    button(page, "Save trade").click().run()

    assert not page.exception
    assert "only 10 held then" in all_text(page)


def test_save_during_an_outage_says_it_was_not_saved(monkeypatch):
    serve(monkeypatch)
    record_changes(monkeypatch, support.DataUnavailable(["Yahoo: down"]))

    page = run_page()
    button(page, "Save trade").click().run()

    assert "Not saved" in all_text(page)


def test_saving_clears_the_cached_valuation(monkeypatch):
    calls = []
    serve(monkeypatch)
    plain_fetch = support.fetch_json

    def counting_fetch(path):
        if path == "/portfolio":
            calls.append(path)
        return plain_fetch(path)

    monkeypatch.setattr(support, "fetch_json", counting_fetch)
    record_changes(monkeypatch)

    page = run_page()
    assert len(calls) == 1
    button(page, "Save trade").click().run()

    assert len(calls) == 2


def test_deleting_a_trade_uses_its_id(monkeypatch):
    serve(monkeypatch, portfolio=make_portfolio(make_holding()), trades=[TRADE])
    sent = record_changes(monkeypatch)

    page = run_page()
    button(page, "Delete trade").click().run()

    assert sent == [("DELETE", "/trades/abc", None)]


def test_adding_a_stock_sends_a_clean_ticker_and_the_fno_choice(monkeypatch):
    serve(monkeypatch)
    sent = record_changes(monkeypatch)

    page = run_page()
    page.text_input[0].set_value(" irctc.ns ")
    page.checkbox[0].set_value(True)
    button(page, "Add to watchlist").click().run()

    assert sent == [("POST", "/stocks", {"ticker": "IRCTC.NS", "is_fno": True})]


def test_add_with_no_ticker_sends_nothing(monkeypatch):
    serve(monkeypatch)
    sent = record_changes(monkeypatch)

    page = run_page()
    button(page, "Add to watchlist").click().run()

    assert sent == []


def test_removing_a_stock_sends_it_to_the_api(monkeypatch):
    serve(monkeypatch)
    sent = record_changes(monkeypatch)

    page = run_page()
    button(page, "Remove from watchlist").click().run()

    assert sent == [("DELETE", "/stocks/TCS.NS", None)]


def page_text(page):
    return " ".join(
        [*(item.value for item in page.caption), *(item.value for item in page.warning)]
    )


def test_insights_shows_the_overview_and_names_a_missing_stock(monkeypatch):
    serve(monkeypatch)

    page = run_page()

    assert not page.exception
    assert {metric.label: metric.value for metric in page.metric}["Rose"] == "1"
    assert "No data for INFY.NS, so it is not counted above." in page_text(page)


def test_news_disclaimer_is_shown(monkeypatch):
    serve(monkeypatch)

    assert "Source: Fake provider. Not checked." in page_text(run_page())


def test_no_news_is_not_shown_as_a_failure(monkeypatch):
    serve(monkeypatch, news={**NEWS, "articles": []})

    page = run_page()

    assert not page.exception
    assert any("does not mean nothing happened" in item.value for item in page.markdown)


def test_failed_news_is_told_apart_from_no_news(monkeypatch):
    serve(monkeypatch, news=support.DataUnavailable(["simulated outage"]))

    assert "News could not be loaded" in page_text(run_page())


def test_a_failed_overview_leaves_the_rest_of_the_page_working(monkeypatch):
    serve(monkeypatch, overview=support.DataUnavailable(["simulated outage"]))

    page = run_page()

    assert not page.exception
    assert "The market overview is unavailable right now." in page_text(page)
    assert "Source: Fake provider. Not checked." in page_text(page)


def test_saved_alerts_are_listed_and_can_be_deleted(monkeypatch):
    serve(monkeypatch, alerts=[ALERT])

    page = run_page()

    assert not page.exception
    assert "Alert to delete" in [box.label for box in page.selectbox]


def test_alert_label_reads_clearly():
    assert support.alert_label(ALERT) == "TCS.NS: Close above 2,500.00"


def test_analytics_table_shows_unknown_values_as_na():
    table = support.analytics_table(OVERVIEW["stocks"])

    assert table.loc["TCS.NS", "SMA 200"] == "n/a"
    assert table.loc["TCS.NS", "From 52W high"] == "-5.00%"

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


def serve(monkeypatch, *, stocks=STOCKS, history=None, metrics=None):
    """Replace the API. An exception given for a value is raised instead of returned."""

    def answer(value):
        if isinstance(value, Exception):
            raise value
        return value

    def fake_fetch(path):
        if path == "/stocks":
            return answer(stocks)
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
    serve(monkeypatch, history=support.DataUnavailable(["Yahoo: down"]), metrics=support.DataUnavailable(["Yahoo: down"]))

    page = run_page()

    assert not page.exception
    assert "No usable price data for TCS.NS" in all_text(page)
    assert "Yahoo: down" in all_text(page)
    assert len(page.metric) == 0


def test_fallback_prices_still_show_when_metrics_are_refused(monkeypatch):
    # This is the real outage case: bhavcopy has prices but no Adj Close.
    history = make_history(notes=["fallback used because Yahoo: down"])
    serve(monkeypatch, history=history, metrics=support.DataUnavailable(["no Adj Close"]))

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

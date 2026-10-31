"""Tests for the public demo. It must show only made-up data and reach nothing real.

The demo changes global settings, so it runs in its own process here. That process
blocks every network connection, so a demo that tried to reach out would fail.
All data below is SYNTHETIC TEST DATA.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest

from analyze_prices import validate_for_analysis
from fetch_prices import validate_history
from market_data import sample

ROOT = Path(__file__).parent.parent
FAKE_SECRET = "FAKE-SECRET-MUST-NOT-SURVIVE"

CHILD = """
import json, os, socket, sys
sys.path.insert(0, ".")

connections = []
real_connect = socket.socket.connect
def refuse(self, address):
    # Windows joins two sockets on this computer for async work, which is not a network.
    if isinstance(address, tuple) and address[0] in ("127.0.0.1", "::1"):
        return real_connect(self, address)
    connections.append(str(address))
    raise OSError("the demo must not use the network")
socket.socket.connect = refuse

from streamlit.testing.v1 import AppTest
page = AppTest.from_file(os.path.abspath("demo_app.py"), default_timeout=120).run()

import api, dashboard_support, database, demo, user_data
from fastapi.testclient import TestClient
from market_data import service
client = TestClient(api.app)

summary = client.get("/summary?ai=true").json()
print("RESULT" + json.dumps({
    "connections": connections,
    "exceptions": [item.value for item in page.exception],
    "warnings": [item.value for item in page.warning],
    "captions": [item.value for item in page.caption],
    "tabs": [tab.label for tab in page.tabs],
    "folder": str(database.DATA_FOLDER),
    "providers": [provider.name for provider in service.PROVIDERS],
    "secrets": {name: os.environ.get(name) for name in demo.SECRET_NAMES},
    "watchlist": list(user_data.load_watchlist()),
    "trades": len(user_data.load_trades()),
    "summary_text": summary["text"],
    "real_ticker_status": client.post("/stocks", json={"ticker": "TCS.NS", "is_fno": True}).status_code,
    "real_ticker_listed": "TCS.NS" in user_data.load_watchlist(),
    "portfolio": client.get("/portfolio").json()["total_market_value"],
    "alert_status": client.post("/alerts/check").status_code,
}))
"""


@pytest.fixture(scope="module")
def demo_run():
    """Run the demo once with fake secrets set, as a VS Code terminal might load them."""
    environment = {
        **os.environ,
        "GEMINI_API_KEY": FAKE_SECRET,
        "TELEGRAM_BOT_TOKEN": FAKE_SECRET,
        "TELEGRAM_CHAT_ID": FAKE_SECRET,
    }
    environment.pop("MARKETPULSE_DEMO", None)
    result = subprocess.run(
        [sys.executable, "-c", CHILD],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=ROOT,
        env=environment,
        timeout=180,
    )
    line = next((item for item in result.stdout.splitlines() if item.startswith("RESULT")), None)
    assert line, result.stderr[-2000:]
    return json.loads(line.removeprefix("RESULT"))


def test_the_demo_page_runs_without_errors(demo_run):
    assert demo_run["exceptions"] == []


def test_the_demo_uses_no_network(demo_run):
    assert demo_run["connections"] == []


def test_every_page_says_it_is_sample_data(demo_run):
    assert any("SAMPLE DATA" in warning for warning in demo_run["warnings"])


def test_prices_name_the_sample_source(demo_run):
    assert any(sample.SOURCE in caption for caption in demo_run["captions"])


def test_only_the_sample_provider_is_used(demo_run):
    assert demo_run["providers"] == [sample.SOURCE]


def test_the_database_is_a_temporary_folder_not_real_data(demo_run):
    folder = Path(demo_run["folder"])

    assert "marketpulse-demo-" in folder.name
    assert ROOT not in folder.parents


def test_keys_are_removed(demo_run):
    assert set(demo_run["secrets"].values()) == {None}


def test_only_made_up_stocks_are_listed(demo_run):
    assert demo_run["watchlist"] == list(sample.STOCKS)


def test_real_stock_prices_are_refused_not_invented(demo_run):
    assert demo_run["real_ticker_status"] == 422
    assert demo_run["real_ticker_listed"] is False


def test_the_sample_portfolio_can_be_valued(demo_run):
    assert demo_run["trades"] == 3
    assert demo_run["portfolio"] is not None


def test_alerts_run_in_the_demo(demo_run):
    assert demo_run["alert_status"] == 200


def test_the_automation_tab_is_only_in_the_demo(demo_run):
    assert "Automation" in demo_run["tabs"]


def test_the_ai_note_is_never_a_real_call(demo_run):
    assert "AI note unavailable: GEMINI_API_KEY is not set" in demo_run["summary_text"]


def test_the_report_names_the_sample_source(demo_run):
    assert sample.SOURCE in demo_run["summary_text"]


@pytest.mark.parametrize("ticker", sample.STOCKS)
@pytest.mark.parametrize("period", sample.BARS)
def test_sample_bars_pass_the_same_checks_as_real_data(ticker, period):
    table = sample.SampleProvider().fetch_daily(ticker, period)
    now = pd.Timestamp.now(tz=sample.TIMEZONE)

    assert validate_history(table, now) == []
    assert validate_for_analysis(table, now) == []
    assert len(table) == sample.BARS[period]


def test_the_source_label_says_it_is_not_real():
    assert "SAMPLE DATA" in sample.SOURCE
    assert "not market prices" in sample.SOURCE


def test_example_note_uses_the_reports_own_values():
    from dashboard_support import example_ai_note

    stocks = [
        {"ticker": "DEMO-A.NS", "change_1d": -0.0234, "rsi_14": 25.9, "problem": None},
        {"ticker": "DEMO-B.NS", "change_1d": None, "rsi_14": None, "problem": "down"},
    ]

    assert example_ai_note(stocks) == "EXAMPLE: DEMO-A.NS changed -2.34% with an RSI of 25.9."
    assert example_ai_note([]) == "EXAMPLE: no stocks to describe."


def test_sample_prices_repeat_exactly():
    assert sample.random_walk("DEMO-ALPHA.NS") == sample.random_walk("DEMO-ALPHA.NS")


def test_a_real_ticker_gets_no_invented_price():
    with pytest.raises(ValueError, match="sample stocks"):
        sample.SampleProvider().fetch_daily("TCS.NS", "1y")


def test_sample_names_cannot_be_mistaken_for_companies():
    assert all(ticker.startswith("DEMO-") for ticker in sample.STOCKS)


def test_sample_headlines_are_labelled():
    articles = sample.SampleProvider().fetch_news("DEMO-ALPHA.NS", 5)

    assert articles
    assert all(article["title"].startswith("SAMPLE headline") for article in articles)


def test_settings_skip_the_env_file_in_the_demo(tmp_path, monkeypatch):
    import settings

    path = tmp_path / ".env"
    path.write_text("MARKETPULSE_TEST_SETTING=abc\n", encoding="utf-8")
    monkeypatch.setenv("MARKETPULSE_DEMO", "1")
    monkeypatch.delenv("MARKETPULSE_TEST_SETTING", raising=False)

    settings.load_env_file(path)

    assert "MARKETPULSE_TEST_SETTING" not in os.environ

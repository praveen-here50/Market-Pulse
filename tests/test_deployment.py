"""Tests for backups, local-only settings and Yahoo's news. These never touch the network.

All data below is SYNTHETIC TEST DATA. The database goes to a temporary folder, set up
in conftest.py.
"""

import sqlite3
import tomllib
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

import backup_data
import database
import user_data
from market_data import yahoo

ROOT = Path(__file__).parent.parent
BUY = {"ticker": "TCS.NS", "side": "buy", "quantity": 7, "price": 1204.3, "trade_date": "2026-01-01"}


def accept(trades):
    pass


def test_a_backup_holds_the_trades(private_user_data):
    saved = user_data.add_trade(BUY, accept)

    target = backup_data.back_up()

    with closing(sqlite3.connect(target)) as copy:
        rows = copy.execute("SELECT id, quantity, price FROM trades").fetchall()
    assert rows == [(saved["id"], 7, 1204.3)]


def test_a_backup_is_not_changed_by_later_trades():
    user_data.add_trade(BUY, accept)
    target = backup_data.back_up()

    user_data.add_trade(BUY, accept)

    with closing(sqlite3.connect(target)) as copy:
        assert copy.execute("SELECT COUNT(*) FROM trades").fetchone()[0] == 1


def test_no_database_means_no_backup_and_none_is_created(private_user_data):
    assert backup_data.back_up() is None
    assert not private_user_data.exists()


def test_only_the_newest_copies_are_kept(private_user_data):
    user_data.load_trades()
    start = datetime(2026, 1, 1)

    for day in range(backup_data.KEEP_COPIES + 5):
        backup_data.back_up(start + timedelta(days=day))

    names = sorted(path.name for path in (private_user_data / "backups").iterdir())
    assert len(names) == backup_data.KEEP_COPIES
    assert names[0] == "marketpulse-20260106-000000.db"


def test_the_real_database_is_never_pruned(private_user_data):
    user_data.load_trades()
    backup_data.back_up()

    assert (private_user_data / database.DATABASE_FILE).exists()


def test_the_dashboard_stays_on_this_computer():
    config = tomllib.loads((ROOT / ".streamlit" / "config.toml").read_text(encoding="utf-8"))

    assert config["server"]["address"] == "127.0.0.1"


def test_the_start_script_keeps_the_api_on_this_computer():
    script = (ROOT / "run_marketpulse.bat").read_text(encoding="utf-8")

    assert "--host 127.0.0.1" in script
    assert "0.0.0.0" not in script


def test_the_private_files_are_ignored_by_git():
    ignored = (ROOT / ".gitignore").read_text(encoding="utf-8").split()

    assert ".env" in ignored
    assert "data/" in ignored


class FakeSearch:
    """Stands in for yf.Search: the first call finds the company, the second its news."""

    def __init__(self, query, max_results, news_count):
        self.quotes = [{"longname": "Infosys Limited"}] if news_count == 0 else []
        self.news = ARTICLES if news_count else []


ARTICLES = [
    {"title": "Infosys wins a deal", "publisher": "Wire A", "providerPublishTime": 1, "link": "https://a.example/1"},
    {"title": "Infosys wins a deal", "publisher": "Wire B", "providerPublishTime": 2, "link": "https://b.example/2"},
    {"title": "Mars launches a snack", "publisher": "Wire C", "providerPublishTime": 3, "link": "https://c.example/3"},
    {"title": "Infosys opens an office", "publisher": "Wire D", "providerPublishTime": 4, "link": "http://d.example/4"},
    {"title": "Infosys hires staff", "publisher": "Wire E", "providerPublishTime": 5, "link": "javascript:alert(1)"},
    {"title": "INFY reports results", "publisher": "Wire F", "providerPublishTime": 6, "link": "https://f.example/6"},
]


def test_news_keeps_relevant_safe_unique_articles(monkeypatch):
    monkeypatch.setattr(yahoo.yf, "Search", FakeSearch)

    articles = yahoo.YahooProvider().fetch_news("INFY.NS", 5)

    assert [article["title"] for article in articles] == ["Infosys wins a deal", "INFY reports results"]
    assert articles[0]["publisher"] == "Wire A"


def test_news_respects_the_limit(monkeypatch):
    monkeypatch.setattr(yahoo.yf, "Search", FakeSearch)

    assert len(yahoo.YahooProvider().fetch_news("INFY.NS", 1)) == 1


def test_an_unknown_company_is_a_failure_not_an_empty_list(monkeypatch):
    monkeypatch.setattr(
        yahoo.yf, "Search", lambda query, max_results, news_count: SimpleNamespace(quotes=[], news=[])
    )

    with pytest.raises(LookupError):
        yahoo.YahooProvider().fetch_news("NOPE.NS", 5)


class FakeTicker:
    def __init__(self, table):
        self.table = table

    def history(self, **options):
        return self.table


def test_splits_are_read_as_dates_and_ratios(monkeypatch):
    table = pd.DataFrame(
        {"Stock Splits": [0.0, 2.0, 0.0]},
        index=pd.date_range("2026-08-25", periods=3, freq="D", tz="Asia/Kolkata"),
    )
    monkeypatch.setattr(yahoo.yf, "Ticker", lambda ticker: FakeTicker(table))

    assert yahoo.YahooProvider().fetch_splits("TCS.NS", "2026-08-01") == {"2026-08-26": 2.0}


def test_an_empty_download_is_a_failure_not_no_splits(monkeypatch):
    monkeypatch.setattr(yahoo.yf, "Ticker", lambda ticker: FakeTicker(pd.DataFrame()))

    with pytest.raises(ConnectionError):
        yahoo.YahooProvider().fetch_splits("TCS.NS", "2026-08-01")

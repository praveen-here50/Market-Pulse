"""Tests for fetch_prices.py. These never touch the network.

All prices below are SYNTHETIC TEST DATA, not real market values. It lets us
create bad data on purpose, which a live API would rarely give us.
"""

import pandas as pd
import pytest

import fetch_prices

NOW = pd.Timestamp("2026-10-30 19:00", tz="Asia/Kolkata")


def make_history():
    """Three valid synthetic daily bars ending on the same date as NOW."""
    dates = pd.date_range("2026-10-28", periods=3, freq="D", tz="Asia/Kolkata")
    return pd.DataFrame(
        {
            "Open": [100.0, 102.0, 101.0],
            "High": [105.0, 106.0, 104.0],
            "Low": [99.0, 101.0, 100.0],
            "Close": [102.0, 103.0, 102.5],
            "Volume": [1000, 1200, 900],
        },
        index=dates,
    )


def test_valid_data_has_no_problems():
    assert fetch_prices.validate_history(make_history(), NOW) == []


def test_tiny_float_noise_is_tolerated():
    history = make_history()
    history.loc[history.index[0], "High"] = 102.0 - 0.000049  # Close is 102.0
    assert fetch_prices.validate_history(history, NOW) == []


def test_empty_table_fails():
    # This is exactly what yfinance returns for an unknown symbol.
    problems = fetch_prices.validate_history(pd.DataFrame(), NOW)
    assert "no rows returned" in problems[0]


def test_missing_column_fails():
    problems = fetch_prices.validate_history(make_history().drop(columns="Volume"), NOW)
    assert problems == ["missing columns: ['Volume']"]


@pytest.mark.parametrize(
    ("column", "value", "expected"),
    [
        ("Close", float("nan"), "missing values"),
        ("Low", 0.0, "zero or negative prices"),
        ("Open", -5.0, "zero or negative prices"),
        ("Volume", -1, "negative volume"),
        ("High", 50.0, "High is below"),
        ("Low", 500.0, "Low is above"),
    ],
)
def test_bad_values_fail(column, value, expected):
    history = make_history().astype({"Volume": "float64"})
    history.loc[history.index[1], column] = value
    problems = fetch_prices.validate_history(history, NOW)
    assert any(expected in problem for problem in problems)


def test_duplicate_dates_fail():
    history = make_history()
    history = pd.concat([history, history.tail(1)])
    problems = fetch_prices.validate_history(history, NOW)
    assert any("duplicate" in problem for problem in problems)


def test_unsorted_dates_fail():
    problems = fetch_prices.validate_history(make_history().iloc[::-1], NOW)
    assert any("ascending" in problem for problem in problems)


def test_future_timestamp_fails():
    earlier_now = NOW - pd.Timedelta(days=2)
    problems = fetch_prices.validate_history(make_history(), earlier_now)
    assert any("future" in problem for problem in problems)


def test_stale_data_fails():
    later_now = NOW + pd.Timedelta(days=30)
    problems = fetch_prices.validate_history(make_history(), later_now)
    assert any("stale" in problem for problem in problems)


def test_normal_weekend_is_not_stale():
    # Friday's bar checked on Sunday evening.
    sunday = pd.Timestamp("2026-11-01 19:00", tz="Asia/Kolkata")
    assert fetch_prices.validate_history(make_history(), sunday) == []


def test_bar_is_in_progress_before_the_close():
    latest = make_history().index.max()
    during_session = pd.Timestamp("2026-10-30 11:00", tz="Asia/Kolkata")
    assert "IN PROGRESS" in fetch_prices.describe_latest_bar(latest, during_session)
    assert fetch_prices.describe_latest_bar(latest, NOW) == "complete daily bar"


def test_bar_is_in_progress_during_the_closing_auction():
    latest = make_history().index.max()
    during_auction = pd.Timestamp("2026-10-30 15:32", tz="Asia/Kolkata")
    assert "IN PROGRESS" in fetch_prices.describe_latest_bar(latest, during_auction)


def test_provider_failure_is_reported_and_other_symbols_continue(monkeypatch, capsys):
    def fake_fetch(symbol):
        if symbol == "TCS.NS":
            raise ConnectionError("simulated outage")
        return make_history()

    monkeypatch.setattr(fetch_prices, "fetch_history", fake_fetch)
    monkeypatch.setattr(fetch_prices.pd.Timestamp, "now", lambda tz=None: NOW)

    assert fetch_prices.main() == 1

    output = capsys.readouterr().out
    assert "3 of 4 symbols passed" in output
    assert "FAILED TCS.NS: download failed: ConnectionError" in output
    assert "RELIANCE.NS" in output


def test_all_symbols_passing_exits_zero(monkeypatch):
    monkeypatch.setattr(fetch_prices, "fetch_history", lambda symbol: make_history())
    monkeypatch.setattr(fetch_prices.pd.Timestamp, "now", lambda tz=None: NOW)
    assert fetch_prices.main() == 0

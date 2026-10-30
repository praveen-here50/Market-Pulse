"""Tests for analyze_prices.py. These never touch the network.

All prices below are SYNTHETIC TEST DATA, not real market values.
"""

import pandas as pd

import analytics
import analyze_prices
import fetch_prices

NOW = pd.Timestamp("2026-10-30 19:00", tz="Asia/Kolkata")
DURING_SESSION = pd.Timestamp("2026-10-30 11:00", tz="Asia/Kolkata")


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


def add_placeholder(history, position):
    """Turn one bar into the flat, zero-volume shape Yahoo uses for a blank day."""
    history = history.copy()
    previous_close = history["Close"].iloc[position - 1]
    for column in ["Open", "High", "Low", "Close", "Adj Close"]:
        history.iloc[position, history.columns.get_loc(column)] = previous_close
    history.iloc[position, history.columns.get_loc("Volume")] = 0
    return history


def use_fake_market(monkeypatch, fake_fetch, now=NOW):
    monkeypatch.setattr(fetch_prices, "fetch_history", fake_fetch)
    monkeypatch.setattr(fetch_prices.pd.Timestamp, "now", lambda tz=None: now)


def test_valid_history_passes():
    assert analyze_prices.validate_for_analysis(make_history(), NOW) == []


def test_phase_1_problems_are_reported():
    problems = analyze_prices.validate_for_analysis(pd.DataFrame(), NOW)
    assert "no rows returned" in problems[0]


def test_missing_adj_close_fails():
    history = make_history().drop(columns="Adj Close")
    assert analyze_prices.validate_for_analysis(history, NOW) == [
        "missing columns: ['Adj Close']"
    ]


def test_bad_adj_close_fails():
    history = make_history()
    history.iloc[3, history.columns.get_loc("Adj Close")] = float("nan")
    problems = analyze_prices.validate_for_analysis(history, NOW)
    assert any("Adj Close" in problem for problem in problems)


def test_prepare_removes_placeholders_and_says_so():
    history = add_placeholder(make_history(), 10)
    cleaned, notes = analyze_prices.prepare_history(history, NOW)
    assert len(cleaned) == 29
    assert history.index[10] not in cleaned.index
    assert notes == ["removed 1 zero-volume placeholder bar(s): 2026-10-11"]


def test_prepare_leaves_out_todays_unfinished_bar():
    cleaned, notes = analyze_prices.prepare_history(make_history(), DURING_SESSION)
    assert cleaned.index[-1] == pd.Timestamp("2026-10-29", tz="Asia/Kolkata")
    assert notes == ["left out today's unfinished bar (2026-10-30)"]


def test_prepare_keeps_a_finished_bar():
    cleaned, notes = analyze_prices.prepare_history(make_history(), NOW)
    assert len(cleaned) == 30
    assert notes == []


def test_unknown_values_are_shown_as_na_not_as_numbers():
    assert analyze_prices.format_metric("SMA 200", float("nan")) == "n/a"
    assert analyze_prices.format_metric("Total return", 0.1234) == "12.34%"
    assert analyze_prices.format_metric("Close", 1234.5) == "1234.50"


def test_every_summary_metric_has_a_format():
    summary = analytics.summarize(make_history())
    assert set(summary) == set(analyze_prices.METRIC_FORMATS)


def test_all_symbols_completing_exits_zero(monkeypatch, capsys):
    use_fake_market(monkeypatch, lambda symbol, period: make_history())

    assert analyze_prices.main() == 0

    output = capsys.readouterr().out
    assert "4 of 4 symbols completed" in output
    assert "not predictions" in output
    assert "RELIANCE.NS" in output


def test_analysis_asks_for_a_full_year(monkeypatch):
    periods = []

    def fake_fetch(symbol, period):
        periods.append(period)
        return make_history()

    use_fake_market(monkeypatch, fake_fetch)
    analyze_prices.main()
    assert set(periods) == {"1y"}


def test_provider_failure_is_reported_and_other_symbols_continue(monkeypatch, capsys):
    def fake_fetch(symbol, period):
        if symbol == "TCS.NS":
            raise ConnectionError("simulated outage")
        return make_history()

    use_fake_market(monkeypatch, fake_fetch)

    assert analyze_prices.main() == 1

    output = capsys.readouterr().out
    assert "3 of 4 symbols completed" in output
    assert "FAILED TCS.NS: analysis failed: ConnectionError" in output
    assert "RELIANCE.NS" in output


def test_all_symbols_failing_prints_no_table(monkeypatch, capsys):
    use_fake_market(monkeypatch, lambda symbol, period: pd.DataFrame())

    assert analyze_prices.main() == 1

    output = capsys.readouterr().out
    assert "0 of 4 symbols completed" in output
    assert "Close" not in output.split("\n\n")[1]


def test_symbol_with_only_an_unfinished_bar_fails_cleanly(monkeypatch, capsys):
    use_fake_market(monkeypatch, lambda symbol, period: make_history(1), now=DURING_SESSION)

    assert analyze_prices.main() == 1
    assert "no complete bars left after cleaning" in capsys.readouterr().out

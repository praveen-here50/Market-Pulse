"""Tests for analytics.py. These never touch the network.

Expected values are worked out by hand in the comments, or copied from a
published example, so that a test cannot pass just by repeating the code's own
answer. All prices are SYNTHETIC TEST DATA unless a test says otherwise.
"""

import math

import pandas as pd
import pytest

import analytics

# Wilder RSI worked example from StockCharts ChartSchool. Sample figures from a
# textbook illustration, not market data for any stock we follow.
RSI_SAMPLE_PRICES = [
    44.3389, 44.0902, 44.1497, 43.6124, 44.3278, 44.8264, 45.0955, 45.4245,
    45.8433, 46.0826, 45.8931, 46.0328, 45.6140, 46.2820, 46.2820, 46.0028,
    46.0328, 46.4116, 46.2222, 45.6439, 46.2122, 46.2521, 45.7137, 46.4515,
    45.7835, 45.3548, 44.0288, 44.1783, 44.2181, 44.5672, 43.4205, 42.6628,
    43.1314,
]  # fmt: skip
RSI_SAMPLE_EXPECTED = [
    70.53, 66.32, 66.55, 69.41, 66.36, 57.97, 62.93, 63.26, 56.06, 62.38,
    54.71, 50.42, 39.99, 41.46, 41.87, 45.46, 37.30, 33.08, 37.77,
]  # fmt: skip


def make_bars(closes, start="2026-01-01", **columns):
    """Build a daily table where Open, High and Low sit around each close."""
    close = pd.Series(closes, dtype="float64")
    table = {
        "Open": close,
        "High": close + 1,
        "Low": close - 1,
        "Close": close,
        "Adj Close": close,
        "Volume": 1000,
        **columns,
    }
    dates = pd.date_range(start, periods=len(close), freq="D", tz="Asia/Kolkata")
    return pd.DataFrame(table).set_index(dates)


def test_placeholder_bars_are_removed_and_reported():
    history = make_bars([100.0, 101.0, 102.0])
    history.iloc[1, history.columns.get_indexer(["Open", "High", "Low", "Close"])] = 100.0
    history.iloc[1, history.columns.get_loc("Volume")] = 0

    cleaned, removed = analytics.remove_placeholder_bars(history)

    assert cleaned["Close"].tolist() == [100.0, 102.0]
    assert list(removed) == [history.index[1]]


def test_zero_volume_bar_with_a_real_range_is_kept():
    # Index bars look like this: no volume reported, but they did move.
    history = make_bars([100.0, 101.0], Volume=0)
    cleaned, removed = analytics.remove_placeholder_bars(history)
    assert len(cleaned) == 2
    assert len(removed) == 0


def test_flat_bar_with_real_volume_is_kept():
    history = make_bars([100.0, 100.0])
    history["High"] = history["Low"] = history["Close"]
    cleaned, _ = analytics.remove_placeholder_bars(history)
    assert len(cleaned) == 2


def test_daily_returns():
    returns = analytics.daily_returns(pd.Series([100.0, 110.0, 99.0]))
    assert math.isnan(returns.iloc[0])
    assert returns.iloc[1:].tolist() == pytest.approx([0.10, -0.10])  # +10 of 100, -11 of 110


def test_daily_returns_do_not_fill_a_gap():
    returns = analytics.daily_returns(pd.Series([100.0, float("nan"), 110.0]))
    assert returns.isna().tolist() == [True, True, True]


def test_period_return():
    assert analytics.period_return(pd.Series([200.0, 150.0, 250.0])) == pytest.approx(0.25)


def test_period_return_needs_two_prices():
    assert math.isnan(analytics.period_return(pd.Series([100.0])))


def test_annualised_volatility():
    # Mean is 0, so sample variance = (0.01^2 + 0.01^2) / (2 - 1) = 0.0002.
    # sqrt(0.0002) * sqrt(252) = sqrt(0.0504) = 0.2244994.
    result = analytics.annualised_volatility(pd.Series([0.01, -0.01]))
    assert result == pytest.approx(0.2244994, abs=1e-7)


def test_volatility_of_one_return_is_unknown():
    assert math.isnan(analytics.annualised_volatility(pd.Series([0.01])))


def test_max_drawdown_measures_from_the_highest_peak():
    # Peak 120, later low 80: 80 / 120 - 1 = -1/3. The first fall to 90 is smaller.
    prices = pd.Series([100.0, 120.0, 90.0, 110.0, 80.0, 100.0])
    assert analytics.max_drawdown(prices) == pytest.approx(-1 / 3)


def test_max_drawdown_is_zero_when_prices_only_rise():
    assert analytics.max_drawdown(pd.Series([100.0, 101.0, 102.0])) == 0


def test_52_week_range_uses_high_and_low_and_ignores_older_bars():
    history = make_bars([500.0] + [100.0, 110.0], start="2025-01-01")
    history.index = pd.DatetimeIndex(
        ["2025-01-01", "2026-09-01", "2026-09-02"], tz="Asia/Kolkata"
    )
    # The 500 bar is older than 52 weeks. The rest have High = close + 1, Low = close - 1.
    assert analytics.high_low_52_weeks(history) == (111.0, 99.0)


def test_sma():
    result = analytics.sma(pd.Series([1.0, 2.0, 3.0, 4.0]), 3)
    assert result.iloc[:2].isna().all()
    assert result.iloc[2:].tolist() == [2.0, 3.0]  # (1+2+3)/3, (2+3+4)/3


def test_ema():
    # span 3 means alpha = 2 / (3 + 1) = 0.5.
    # 10, then 0.5*11 + 0.5*10 = 10.5, then 0.5*12 + 0.5*10.5 = 11.25.
    result = analytics.ema(pd.Series([10.0, 11.0, 12.0]), 3)
    assert result.iloc[:2].isna().all()
    assert result.iloc[2] == pytest.approx(11.25)


def test_rsi_matches_the_published_worked_example():
    result = analytics.rsi(pd.Series(RSI_SAMPLE_PRICES))
    assert result.iloc[:14].isna().all()
    assert result.iloc[14:].round(2).tolist() == RSI_SAMPLE_EXPECTED


def test_rsi_is_100_when_prices_only_rise():
    assert analytics.rsi(pd.Series(range(100, 120), dtype="float64")).iloc[-1] == 100


def test_rsi_is_0_when_prices_only_fall():
    assert analytics.rsi(pd.Series(range(120, 100, -1), dtype="float64")).iloc[-1] == 0


def test_rsi_is_unknown_when_prices_never_move():
    assert math.isnan(analytics.rsi(pd.Series([100.0] * 20)).iloc[-1])


def test_rsi_needs_one_more_price_than_its_window():
    assert analytics.rsi(pd.Series([100.0 + i for i in range(14)])).isna().all()
    assert analytics.rsi(pd.Series([100.0 + i for i in range(15)])).iloc[-1] == 100


def test_summary_separates_price_return_from_total_return():
    # The price did not move, but Adj Close credits a 1% dividend on the last day.
    history = make_bars([100.0, 100.0, 100.0], **{"Adj Close": [99.0, 99.0, 100.0]})
    summary = analytics.summarize(history)
    assert summary["Price return"] == 0
    assert summary["Total return"] == pytest.approx(1 / 99)
    assert summary["1D change"] == 0
    assert summary["Max drawdown"] == 0


def test_summary_does_not_count_an_ex_dividend_drop_as_a_loss():
    # Close falls 10 because a 10 dividend was paid. Adj Close shows the holder lost nothing.
    history = make_bars([100.0, 100.0, 90.0], **{"Adj Close": [90.0, 90.0, 90.0]})
    summary = analytics.summarize(history)
    assert summary["1D change"] == pytest.approx(-0.10)  # the move people saw on screen
    assert summary["Max drawdown"] == 0
    assert summary["Volatility (ann.)"] == 0


def test_summary_leaves_indicators_empty_without_enough_history():
    summary = analytics.summarize(make_bars([100.0 + i for i in range(30)]))
    assert summary["Bars used"] == 30
    assert summary["SMA 20"] == pytest.approx(119.5)  # mean of 110 to 129
    assert math.isnan(summary["SMA 50"])
    assert math.isnan(summary["SMA 200"])

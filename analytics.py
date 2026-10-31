"""MarketPulse Phase 2: clean daily price tables and calculate metrics from them.

Nothing here touches the network, so every formula can be tested against known
values. Results are fractions (0.05 means 5%). When there is too little data
for a calculation the result is NaN, never a guess.

These numbers describe past prices. They are not predictions or advice.
"""

import math

import pandas as pd

# The usual convention, kept so our volatility compares with published figures.
# NSE itself trades slightly fewer days (247 in the year to Oct 2026).
TRADING_DAYS_PER_YEAR = 252

SMA_WINDOWS = (20, 50, 200)
EMA_SPAN = 20
RSI_WINDOW = 14


def remove_placeholder_bars(history):
    """Split off bars where no trade happened. Return (kept bars, removed dates).

    Yahoo sometimes fills a day with Volume 0 and Open, High, Low and Close all
    equal to the previous close. That is not a price: left in, it counts as a
    0% day and drags down volatility and moving averages.

    Volume 0 alone is not enough, because Yahoo reports no volume at all for
    indices, whose bars still have a real High and Low.
    """
    is_placeholder = (history["Volume"] == 0) & (history["High"] == history["Low"])
    return history[~is_placeholder], history.index[is_placeholder]


def daily_returns(prices):
    """Return each bar's percentage change. The first bar has none, so it is NaN.

    fill_method=None stops pandas from quietly filling gaps in the prices.
    """
    return prices.pct_change(fill_method=None)


def period_return(prices):
    """Return the change from the first price to the last."""
    if len(prices) < 2:
        return math.nan
    return prices.iloc[-1] / prices.iloc[0] - 1


def annualised_volatility(returns):
    """Scale the standard deviation of daily returns up to one year.

    Daily moves add up like a random walk, so the spread grows with the square
    root of time, not with time itself.
    """
    return returns.std() * math.sqrt(TRADING_DAYS_PER_YEAR)


def max_drawdown(prices):
    """Return the worst fall from a previous peak, as a negative fraction."""
    return (prices / prices.cummax() - 1).min()


def high_low_52_weeks(history):
    """Return the highest High and lowest Low of the 52 weeks up to the last bar."""
    start = history.index[-1] - pd.Timedelta(weeks=52)
    recent = history[history.index > start]
    return recent["High"].max(), recent["Low"].min()


def sma(prices, window):
    """Return the simple moving average: the plain mean of the last `window` prices."""
    return prices.rolling(window).mean()


def ema(prices, span):
    """Return the exponential moving average, which weights recent prices more.

    It starts from the first price. Charting sites often start from an SMA
    instead, but the two agree once a few multiples of `span` have passed.
    """
    return prices.ewm(span=span, adjust=False, min_periods=span).mean()


def _wilder_average(values, window):
    """Return Wilder's running average of `values`, which start at position 1.

    The first result is the plain mean of the first `window` values. After that
    each result is (previous * (window - 1) + new value) / window, which is what
    ewm(alpha=1/window, adjust=False) calculates when given that starting value.
    """
    if len(values) <= window:
        return pd.Series(math.nan, index=values.index)

    seeded = values.iloc[window:].copy()
    seeded.iloc[0] = values.iloc[1 : window + 1].mean()
    return seeded.ewm(alpha=1 / window, adjust=False).mean().reindex(values.index)


def rsi(prices, window=RSI_WINDOW):
    """Return Wilder's Relative Strength Index, from 0 to 100.

    It compares the average size of recent gains and losses. Prices that never
    moved have neither, so the result there is NaN rather than an invented 50.
    """
    changes = prices.diff()
    average_gain = _wilder_average(changes.clip(lower=0), window)
    average_loss = _wilder_average(-changes.clip(upper=0), window)
    return 100 * average_gain / (average_gain + average_loss)


def summarize(history):
    """Return one symbol's metrics as a dict, from bars that are already clean.

    Returns and risk use Adj Close, so an ex-dividend drop is not counted as a
    loss. Indicators use Close, so they match the prices people see on charts.
    """
    close = history["Close"]
    adjusted = history["Adj Close"]
    week_52_high, week_52_low = high_low_52_weeks(history)

    summary = {
        "Bars used": len(history),
        "First bar": history.index[0],
        "Last bar": history.index[-1],
        "Close": close.iloc[-1],
        "1D change": daily_returns(close).iloc[-1],
        "Price return": period_return(close),
        "Total return": period_return(adjusted),
        "Volatility (ann.)": annualised_volatility(daily_returns(adjusted)),
        "Max drawdown": max_drawdown(adjusted),
        "52W high": week_52_high,
        "52W low": week_52_low,
    }
    for window in SMA_WINDOWS:
        summary[f"SMA {window}"] = sma(close, window).iloc[-1]
    summary[f"EMA {EMA_SPAN}"] = ema(close, EMA_SPAN).iloc[-1]
    summary[f"RSI {RSI_WINDOW}"] = rsi(close).iloc[-1]
    return summary


def distance_from_high(close, high):
    """Return how far a close is below a high, as a negative fraction, or None if unknown."""
    if close is None or high is None:
        return None
    return close / high - 1


def count_moves(changes):
    """Count rises, falls and flat days. An unknown change is in none of them."""
    known = [change for change in changes if change is not None]
    return {
        "advancers": sum(change > 0 for change in known),
        "decliners": sum(change < 0 for change in known),
        "unchanged": sum(change == 0 for change in known),
    }

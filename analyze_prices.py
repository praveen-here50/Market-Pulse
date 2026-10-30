"""MarketPulse Phase 2: compare one year of metrics for four NSE stocks.

Run with:  python analyze_prices.py
Exit code: 0 if every symbol was analysed, 1 if any symbol failed.
"""

import sys

import pandas as pd

import analytics
import fetch_prices
from market_data.instruments import market_close_for
from market_data.service import fetch_with_fallback

# One year gives about 247 bars: enough for SMA 200 and for 52-week levels.
ANALYSIS_PERIOD = "1y"

METRIC_FORMATS = {
    "Source": "{}",
    "Bars used": "{:d}",
    "First bar": "{:%Y-%m-%d}",
    "Last bar": "{:%Y-%m-%d}",
    "Close": "{:.2f}",
    "1D change": "{:.2%}",
    "Price return": "{:.2%}",
    "Total return": "{:.2%}",
    "Volatility (ann.)": "{:.2%}",
    "Max drawdown": "{:.2%}",
    "52W high": "{:.2f}",
    "52W low": "{:.2f}",
    "SMA 20": "{:.2f}",
    "SMA 50": "{:.2f}",
    "SMA 200": "{:.2f}",
    "EMA 20": "{:.2f}",
    "RSI 14": "{:.1f}",
}


def validate_for_analysis(history, now):
    """Run Phase 1's checks, then check the one extra column we calculate from."""
    problems = fetch_prices.validate_history(history, now)
    if problems:
        return problems

    if "Adj Close" not in history.columns:
        return ["missing columns: ['Adj Close']"]
    if history["Adj Close"].isna().any() or (history["Adj Close"] <= 0).any():
        return ["Adj Close contains missing or non-positive values"]
    return []


def prepare_history(history, now, market_close):
    """Return (bars that are safe to calculate on, notes about what was removed)."""
    cleaned, removed = analytics.remove_placeholder_bars(history)
    notes = []

    if len(removed) > 0:
        dates = ", ".join(f"{date:%Y-%m-%d}" for date in removed)
        notes.append(f"removed {len(removed)} zero-volume placeholder bar(s): {dates}")

    if not cleaned.empty and fetch_prices.is_bar_in_progress(
        cleaned.index[-1], now, market_close
    ):
        notes.append(f"left out today's unfinished bar ({cleaned.index[-1]:%Y-%m-%d})")
        cleaned = cleaned.iloc[:-1]

    return cleaned, notes


def format_metric(name, value):
    """Return a metric as text. A value we could not calculate is shown as n/a."""
    if pd.isna(value):
        return "n/a"
    return METRIC_FORMATS[name].format(value)


def build_table(summaries):
    """Return a table of formatted metrics with one column per symbol."""
    return pd.DataFrame(
        {
            symbol: {name: format_metric(name, value) for name, value in summary.items()}
            for symbol, summary in summaries.items()
        }
    )


def main():
    now = pd.Timestamp.now(tz=fetch_prices.MARKET_TIMEZONE)
    summaries = {}
    notes = {}
    failed = {}

    print(f"MarketPulse Phase 2 | fetched at {now:%Y-%m-%d %H:%M:%S %Z}")
    print("Daily bars, not live quotes. Neither provider is a real-time exchange feed.")
    print("Prices in INR. Returns and risk include dividends; indicators use the traded Close.")
    print("Indicators describe past prices. They are not predictions or financial advice.")

    for symbol in fetch_prices.SYMBOLS:
        # One broken symbol should not stop the others from being reported.
        try:
            result = fetch_with_fallback(
                symbol, ANALYSIS_PERIOD, lambda table: validate_for_analysis(table, now)
            )
            problems = result.failures if result.history is None else []
            if not problems:
                cleaned, symbol_notes = prepare_history(
                    result.history, now, market_close_for(symbol)
                )
                symbol_notes += [f"fallback used because {item}" for item in result.failures]
                if cleaned.empty:
                    problems = ["no complete bars left after cleaning"]
                else:
                    summaries[symbol] = {"Source": result.source, **analytics.summarize(cleaned)}
                    notes[symbol] = symbol_notes
        except Exception as error:
            problems = [f"analysis failed: {type(error).__name__}: {error}"]

        if problems:
            failed[symbol] = problems

    if summaries:
        print(f"\n{build_table(summaries).to_string()}")

    for symbol, symbol_notes in notes.items():
        for note in symbol_notes:
            print(f"Note {symbol}: {note}")

    print(f"\nAnalysis: {len(summaries)} of {len(fetch_prices.SYMBOLS)} symbols completed")
    for symbol, problems in failed.items():
        print(f"  FAILED {symbol}: {'; '.join(problems)}")

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

"""MarketPulse Phase 3: compare Yahoo with hand-downloaded NSE bhavcopy files.

Run with:  python check_providers.py
Exit code: 0 if every symbol was compared and agreed, 1 otherwise.
"""

import sys

import analytics
from market_data.bhavcopy import BHAVCOPY_FOLDER, BhavcopyFileProvider
from market_data.compare import compare_closes
from market_data.instruments import INSTRUMENTS
from market_data.yahoo import YahooProvider

COMPARISON_PERIOD = "2y"


def check_symbol(ticker, yahoo, bhavcopy):
    """Return (lines to print, True if this symbol was compared and agreed)."""
    reference = bhavcopy.read_bars(ticker)
    if reference.empty:
        return [f"{ticker}: no bars found in the bhavcopy files"], False

    primary, _ = analytics.remove_placeholder_bars(yahoo.fetch_daily(ticker, COMPARISON_PERIOD))
    result = compare_closes(primary, reference)

    lines = [f"{ticker}: {result.sessions_compared} session(s) compared"]
    for date, row in result.close_differences.iterrows():
        lines.append(
            f"  {date:%Y-%m-%d} close differs: Yahoo {row['Primary']:.2f}, "
            f"NSE {row['Reference']:.2f} (a split, or a data error)"
        )
    for date in result.missing_from_primary:
        lines.append(f"  {date:%Y-%m-%d} traded on NSE but has no real bar on Yahoo")

    return lines, result.close_differences.empty and result.missing_from_primary.empty


def main():
    yahoo = YahooProvider()
    bhavcopy = BhavcopyFileProvider()
    all_agreed = True

    print(f"Comparing Yahoo with bhavcopy files in {BHAVCOPY_FOLDER}")
    print("Both are end-of-day data, so this checks past closes, not live prices.")

    for ticker in INSTRUMENTS:
        # One broken symbol should not stop the others from being reported.
        try:
            lines, agreed = check_symbol(ticker, yahoo, bhavcopy)
        except Exception as error:
            lines, agreed = [f"{ticker}: check failed: {type(error).__name__}: {error}"], False

        print("\n".join(lines))
        all_agreed = all_agreed and agreed

    print(f"\nResult: {'all sources agree' if all_agreed else 'see the lines above'}")
    return 0 if all_agreed else 1


if __name__ == "__main__":
    sys.exit(main())

"""Try each provider in turn until one returns data that passes our checks."""

from dataclasses import dataclass, field

import pandas as pd

from market_data.bhavcopy import BhavcopyFileProvider
from market_data.yahoo import YahooProvider

PROVIDERS = [YahooProvider(), BhavcopyFileProvider()]


@dataclass
class FetchResult:
    history: pd.DataFrame | None
    source: str | None
    failures: list = field(default_factory=list)


def fetch_with_fallback(ticker, period, check):
    """Return the first provider's data that `check` accepts.

    `check` takes a table and returns a list of problems, so each caller decides
    what it needs. Failures of earlier providers stay in the result, so a
    fallback is always visible to the reader. If every provider fails, history
    is None: there is no invented or partial answer.
    """
    failures = []
    for provider in PROVIDERS:
        # One broken provider should not stop the next one from being tried.
        try:
            history = provider.fetch_daily(ticker, period)
            problems = check(history)
        except Exception as error:
            problems = [f"download failed: {type(error).__name__}: {error}"]

        if not problems:
            return FetchResult(history, provider.name, failures)
        failures.append(f"{provider.name}: {'; '.join(problems)}")

    return FetchResult(None, None, failures)

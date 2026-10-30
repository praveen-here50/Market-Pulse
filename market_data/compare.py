"""Compare two price tables for the same stock."""

from dataclasses import dataclass

import pandas as pd

CLOSE_TOLERANCE = 0.01


@dataclass
class Comparison:
    sessions_compared: int
    close_differences: pd.DataFrame
    missing_from_primary: pd.DatetimeIndex


def compare_closes(primary, reference):
    """Compare closes on shared dates and list sessions only `reference` has.

    Pass `primary` after removing placeholder bars, so that a session Yahoo only
    filled with a placeholder is reported as missing.

    Volume is left out on purpose: Yahoo's newest bar can be a little below
    NSE's final figure even when every price matches.
    """
    shared = primary.index.intersection(reference.index)
    closes = pd.DataFrame(
        {"Primary": primary.loc[shared, "Close"], "Reference": reference.loc[shared, "Close"]}
    )
    is_different = (closes["Primary"] - closes["Reference"]).abs() > CLOSE_TOLERANCE
    return Comparison(
        sessions_compared=len(shared),
        close_differences=closes[is_different],
        missing_from_primary=reference.index.difference(primary.index),
    )

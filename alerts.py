"""MarketPulse Phase 11: tell the owner when a stock reaches a level they chose.

Levels are the owner's own, not signals. Alerts use the last finished session, so they
are never about a live price. Each one fires when its condition becomes true, and
fires again only after the condition has stopped being true.
"""

import uuid
from contextlib import closing

import database

# Each kind names the metric it reads, how it compares, and how it reads in a message.
KINDS = {
    "close_above": ("Close above", "close", lambda value, level: value > level),
    "close_below": ("Close below", "close", lambda value, level: value < level),
    "move_at_least": ("1D move of at least (%)", "move", lambda value, level: value >= level),
    "rsi_above": ("RSI 14 above", "rsi", lambda value, level: value > level),
    "rsi_below": ("RSI 14 below", "rsi", lambda value, level: value < level),
}


def read_value(kind, metrics):
    """Return the number an alert compares, or None if it could not be calculated."""
    source = KINDS[kind][1]
    if source == "close":
        return metrics.close
    if source == "rsi":
        return metrics.rsi_14
    # A fall counts as a move, so the size of the change is what matters.
    return None if metrics.change_1d is None else round(abs(metrics.change_1d) * 100, 2)


def is_met(alert, metrics):
    """Return True or False, or None if the value is unknown. Unknown is never a match."""
    value = read_value(alert["kind"], metrics)
    return None if value is None else KINDS[alert["kind"]][2](value, alert["threshold"])


def describe(alert, metrics):
    label = KINDS[alert["kind"]][0]
    value = read_value(alert["kind"], metrics)
    return (
        f"{alert['ticker']}: {label} {alert['threshold']:,.2f} reached, "
        f"value {value:,.2f} on {metrics.last_bar}"
    )


def load_alerts():
    with closing(database.connect()) as connection:
        rows = connection.execute(
            "SELECT id, ticker, kind, threshold, was_met, last_checked_bar "
            "FROM alerts ORDER BY position"
        )
        return [{**dict(row), "was_met": bool(row["was_met"])} for row in rows]


def add_alert(ticker, kind, threshold):
    alert = {"id": uuid.uuid4().hex, "ticker": ticker, "kind": kind, "threshold": threshold}
    with database.transaction() as connection:
        connection.execute(
            "INSERT INTO alerts (id, ticker, kind, threshold) "
            "VALUES (:id, :ticker, :kind, :threshold)",
            alert,
        )
    return {**alert, "was_met": False, "last_checked_bar": None}


def delete_alert(alert_id):
    """Delete an alert. Return False if it does not exist."""
    with database.transaction() as connection:
        return connection.execute("DELETE FROM alerts WHERE id = ?", (alert_id,)).rowcount == 1


def record_check(alert, last_bar, met):
    """Save a result, and return True if this call is the one that should fire.

    The update only applies once per bar, so two checks running together, or a retry
    after a timeout, cannot send the same alert twice.
    """
    with database.transaction() as connection:
        updated = connection.execute(
            "UPDATE alerts SET was_met = ?, last_checked_bar = ? "
            "WHERE id = ? AND last_checked_bar IS NOT ?",
            (met, last_bar, alert["id"], last_bar),
        )
        return updated.rowcount == 1 and met and not alert["was_met"]

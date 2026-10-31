"""Tests for database.py, above all the import of Phase 6 JSON files.

Trades below are SYNTHETIC TEST DATA. The database goes to a temporary folder,
set up in conftest.py.
"""

import json
import os
import sqlite3
import subprocess
import sys
import threading
from contextlib import closing
from pathlib import Path

import pytest

import database
import portfolio
import user_data

WATCHLIST = [
    {"ticker": "TCS.NS", "is_fno": True},
    {"ticker": "IRCTC.NS", "is_fno": False},
    {"ticker": "M&M.NS", "is_fno": True},
]
TRADES = [
    {"id": "b", "ticker": "TCS.NS", "side": "buy", "quantity": 10, "price": 1204.3, "trade_date": "2026-03-02"},
    {"id": "a", "ticker": "TCS.NS", "side": "sell", "quantity": 4, "price": 1333.37, "trade_date": "2026-03-02"},
    {"id": "c", "ticker": "M&M.NS", "side": "buy", "quantity": 3, "price": 0.1, "trade_date": "2026-01-15"},
]


def write_files(folder, watchlist=WATCHLIST, trades=TRADES):
    folder.mkdir(exist_ok=True)
    if watchlist is not None:
        (folder / "watchlist.json").write_text(json.dumps(watchlist, indent=2), encoding="utf-8")
    if trades is not None:
        (folder / "trades.json").write_text(json.dumps(trades, indent=2), encoding="utf-8")


def test_no_files_gives_the_default_stocks_and_no_trades():
    assert list(user_data.load_watchlist()) == ["RELIANCE.NS", "TCS.NS", "INFY.NS", "HDFCBANK.NS"]
    assert user_data.load_trades() == []


def test_import_keeps_every_trade_exactly_and_in_entry_order(private_user_data):
    write_files(private_user_data)

    # Not sorted by date or id: same-day trades must replay in the order entered.
    assert user_data.load_trades() == TRADES


def test_import_keeps_the_watchlist_and_its_order(private_user_data):
    write_files(private_user_data)

    watchlist = user_data.load_watchlist()

    assert list(watchlist) == ["TCS.NS", "IRCTC.NS", "M&M.NS"]
    assert watchlist["IRCTC.NS"].is_fno is False
    assert watchlist["M&M.NS"].nse_symbol == "M&M"


def test_import_keeps_the_watchlist_when_there_are_no_trades(private_user_data):
    write_files(private_user_data, trades=None)

    assert list(user_data.load_watchlist()) == ["TCS.NS", "IRCTC.NS", "M&M.NS"]


def test_import_uses_the_defaults_when_only_trades_exist(private_user_data):
    # Phase 6 only wrote watchlist.json after the watchlist was first changed.
    tcs_trades = TRADES[:2]
    write_files(private_user_data, watchlist=None, trades=tcs_trades)

    assert "RELIANCE.NS" in user_data.load_watchlist()
    assert user_data.load_trades() == tcs_trades


def test_holdings_are_the_same_after_the_import(private_user_data):
    write_files(private_user_data)
    tcs = [trade for trade in user_data.load_trades() if trade["ticker"] == "TCS.NS"]

    position = portfolio.replay(tcs, {})

    # 10 at 1204.30, then 4 sold at 1333.37: 6 left, gain of 4 x 129.07.
    assert position.quantity == 6
    assert position.realised == pytest.approx(516.28)


def test_import_leaves_the_files_untouched(private_user_data):
    write_files(private_user_data)
    before = (private_user_data / "trades.json").read_bytes()

    user_data.load_trades()

    assert (private_user_data / "trades.json").read_bytes() == before


def test_import_happens_only_once(private_user_data):
    write_files(private_user_data)
    user_data.delete_trade("c", lambda trades: None)

    assert [trade["id"] for trade in user_data.load_trades()] == ["b", "a"]


def test_damaged_file_stops_the_import_and_nothing_is_half_saved(private_user_data):
    write_files(private_user_data, trades=None)
    damaged = private_user_data / "trades.json"
    damaged.write_text('[{"ticker": "TCS', encoding="utf-8")

    with pytest.raises(json.JSONDecodeError):
        user_data.load_watchlist()
    assert damaged.read_text(encoding="utf-8") == '[{"ticker": "TCS'

    # The valid watchlist file must not have been saved on its own. Once the file
    # is repaired the import runs again, because nothing counted as finished.
    write_files(private_user_data)
    assert user_data.load_trades() == TRADES
    assert list(user_data.load_watchlist()) == ["TCS.NS", "IRCTC.NS", "M&M.NS"]


def test_a_bad_trade_undoes_the_whole_import(private_user_data):
    write_files(private_user_data, trades=[*TRADES, {**TRADES[0], "id": "d", "quantity": -1}])

    with pytest.raises(sqlite3.IntegrityError):
        user_data.load_trades()

    write_files(private_user_data)
    assert user_data.load_trades() == TRADES


def test_trades_for_a_stock_not_on_the_watchlist_are_named(private_user_data):
    write_files(private_user_data, watchlist=WATCHLIST[:1])

    with pytest.raises(ValueError, match=r"M&M\.NS"):
        user_data.load_trades()


def test_threads_starting_together_import_once(private_user_data):
    write_files(private_user_data)
    errors = []

    def read():
        try:
            user_data.load_trades()
        except Exception as error:
            errors.append(error)

    threads = [threading.Thread(target=read) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    assert user_data.load_trades() == TRADES


def test_damaged_database_raises_and_is_never_overwritten(private_user_data):
    private_user_data.mkdir()
    damaged = private_user_data / database.DATABASE_FILE
    damaged.write_bytes(b"this is not a database file, " * 100)
    before = damaged.read_bytes()

    with pytest.raises(sqlite3.DatabaseError):
        user_data.add_trade(TRADES[0], lambda trades: None)

    assert damaged.read_bytes() == before


def test_database_from_a_newer_version_is_refused(private_user_data):
    user_data.load_trades()
    with closing(sqlite3.connect(private_user_data / database.DATABASE_FILE)) as connection:
        connection.execute(f"PRAGMA user_version = {database.SCHEMA_VERSION + 1}")

    with pytest.raises(RuntimeError, match="expects 1"):
        user_data.load_trades()


def test_a_failed_transaction_saves_nothing():
    with pytest.raises(ZeroDivisionError):
        with database.transaction() as connection:
            connection.execute("DELETE FROM watchlist")
            1 / 0

    assert len(user_data.load_watchlist()) == 4


def test_the_data_folder_can_be_moved_for_testing(tmp_path):
    code = "import database; print(database.DATA_FOLDER)"
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=True,
        cwd=Path(database.__file__).parent,
        env={**os.environ, "MARKETPULSE_DATA_FOLDER": str(tmp_path)},
    )

    assert result.stdout.strip() == str(tmp_path)

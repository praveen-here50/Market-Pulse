"""Tests for user_data.py. The database goes to a temporary folder, set up in conftest.py."""

import sqlite3
import threading

import pytest

import database
import user_data

BUY = {"ticker": "TCS.NS", "side": "buy", "quantity": 1, "price": 100.0, "trade_date": "2026-01-01"}


def accept(trades):
    pass


def refuse(trades):
    raise user_data.Rejected("no")


def test_tests_cannot_reach_the_real_data_folder(private_user_data):
    assert database.DATA_FOLDER == private_user_data
    assert "pytest" in str(private_user_data).lower()


def test_watchlist_starts_with_the_four_default_stocks():
    assert list(user_data.load_watchlist()) == ["RELIANCE.NS", "TCS.NS", "INFY.NS", "HDFCBANK.NS"]


def test_added_stock_keeps_its_closing_time():
    user_data.add_stock("IRCTC.NS", is_fno=False)
    instrument = user_data.load_watchlist()["IRCTC.NS"]
    assert instrument.nse_symbol == "IRCTC"
    assert instrument.market_close.strftime("%H:%M") == "15:30"


def test_adding_a_stock_twice_is_rejected():
    with pytest.raises(user_data.Rejected, match="already"):
        user_data.add_stock("TCS.NS", is_fno=True)


def test_removing_a_stock():
    user_data.remove_stock("TCS.NS")
    assert "TCS.NS" not in user_data.load_watchlist()


def test_a_stock_with_trades_cannot_be_removed():
    user_data.add_trade(BUY, accept)
    with pytest.raises(user_data.Rejected, match="has trades"):
        user_data.remove_stock("TCS.NS")
    assert "TCS.NS" in user_data.load_watchlist()


def test_trades_are_saved_and_get_an_id():
    saved = user_data.add_trade(BUY, accept)
    assert saved["id"]
    assert user_data.load_trades() == [saved]


def test_trades_survive_a_restart(private_user_data):
    saved = user_data.add_trade(BUY, accept)

    with sqlite3.connect(private_user_data / database.DATABASE_FILE) as connection:
        rows = connection.execute("SELECT id, quantity, price FROM trades").fetchall()
    connection.close()

    assert rows == [(saved["id"], 1, 100.0)]


def test_trades_keep_their_entry_order_after_a_delete():
    first = user_data.add_trade(BUY, accept)
    second = user_data.add_trade(BUY, accept)
    user_data.delete_trade(first["id"], accept)
    third = user_data.add_trade(BUY, accept)

    assert user_data.load_trades() == [second, third]


def test_check_sees_the_saved_trades_and_the_new_one():
    first = user_data.add_trade(BUY, accept)
    seen = []
    second = user_data.add_trade(BUY, seen.extend)

    assert seen == [first, second]


def test_refused_trade_is_not_saved():
    with pytest.raises(user_data.Rejected):
        user_data.add_trade(BUY, refuse)
    assert user_data.load_trades() == []


def test_delete_trade():
    saved = user_data.add_trade(BUY, accept)
    assert user_data.delete_trade(saved["id"], accept) is True
    assert user_data.load_trades() == []


def test_refused_delete_keeps_the_trade():
    saved = user_data.add_trade(BUY, accept)
    with pytest.raises(user_data.Rejected):
        user_data.delete_trade(saved["id"], refuse)
    assert len(user_data.load_trades()) == 1


def test_deleting_an_unknown_trade_reports_it():
    assert user_data.delete_trade("nope", accept) is False


def test_trades_for_an_unknown_stock_are_refused_by_the_database():
    with pytest.raises(sqlite3.IntegrityError):
        user_data.add_trade({**BUY, "ticker": "NOPE.NS"}, accept)


def test_a_bad_value_is_refused_by_the_database():
    with pytest.raises(sqlite3.IntegrityError):
        user_data.add_trade({**BUY, "quantity": 0}, accept)
    assert user_data.load_trades() == []


def test_saves_from_many_threads_are_all_kept():
    threads = [
        threading.Thread(target=user_data.add_trade, args=(BUY, accept)) for _ in range(20)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(user_data.load_trades()) == 20

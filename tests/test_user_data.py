"""Tests for user_data.py. Files go to a temporary folder, set up in conftest.py."""

import json

import pytest

import user_data

BUY = {"ticker": "TCS.NS", "side": "buy", "quantity": 1, "price": 100.0, "trade_date": "2026-01-01"}


def accept(trades):
    pass


def refuse(trades):
    raise user_data.Rejected("no")


def test_tests_cannot_reach_the_real_data_folder(private_user_data):
    assert user_data.DATA_FOLDER == private_user_data
    assert "pytest" in str(private_user_data).lower()


def test_watchlist_starts_with_the_four_default_stocks():
    assert list(user_data.load_watchlist()) == ["RELIANCE.NS", "TCS.NS", "INFY.NS", "HDFCBANK.NS"]


def test_loading_does_not_create_files(private_user_data):
    user_data.load_watchlist()
    user_data.load_trades()
    assert not private_user_data.exists()


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
    assert json.loads((private_user_data / "trades.json").read_text()) == [saved]


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


def test_damaged_file_raises_and_is_never_overwritten(private_user_data):
    private_user_data.mkdir()
    damaged = private_user_data / "trades.json"
    damaged.write_text('[{"ticker": "TCS', encoding="utf-8")

    with pytest.raises(json.JSONDecodeError):
        user_data.add_trade(BUY, accept)

    assert damaged.read_text(encoding="utf-8") == '[{"ticker": "TCS'


def test_no_temporary_file_is_left_behind(private_user_data):
    user_data.add_trade(BUY, accept)
    assert [path.name for path in private_user_data.iterdir()] == ["trades.json"]

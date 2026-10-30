"""Tests for portfolio.py. Expected values are worked out by hand in the comments.

All trades and prices below are SYNTHETIC TEST DATA.
"""

import pytest

from portfolio import InvalidTrades, replay


def trade(side, quantity, price, date="2026-01-10"):
    return {"side": side, "quantity": quantity, "price": price, "trade_date": date}


def test_no_trades_means_nothing_held():
    position = replay([], {})
    assert position.quantity == 0
    assert position.average_cost is None


def test_buying_twice_averages_the_cost():
    # 10 at 100 is 1,000. 10 at 200 is 2,000. 3,000 for 20 shares is 150 each.
    position = replay([trade("buy", 10, 100.0), trade("buy", 10, 200.0)], {})
    assert position.quantity == 20
    assert position.cost == 3000
    assert position.average_cost == 150


def test_selling_books_profit_against_the_average_cost():
    # 5 sold at 180 against an average of 150 makes 5 * 30 = 150.
    trades = [trade("buy", 10, 100.0), trade("buy", 10, 200.0), trade("sell", 5, 180.0, "2026-01-11")]
    position = replay(trades, {})
    assert position.realised == pytest.approx(150)
    assert position.quantity == 15
    assert position.cost == pytest.approx(2250)  # 15 * 150
    assert position.average_cost == pytest.approx(150)


def test_selling_at_a_loss_is_negative():
    # 4 * (90 - 100) = -40.
    position = replay([trade("buy", 10, 100.0), trade("sell", 4, 90.0, "2026-01-11")], {})
    assert position.realised == pytest.approx(-40)


def test_selling_everything_in_parts_leaves_no_float_dust():
    # Without the reset, these exact numbers leave a cost of about -0.0000000000018.
    trades = [
        trade("buy", 11, 2388.81, "2026-01-01"),
        trade("buy", 14, 776.0, "2026-01-10"),
        trade("sell", 10.17, 1000.0, "2026-01-11"),
        trade("sell", 10.17, 1000.0, "2026-01-12"),
        trade("sell", 10.16, 1000.0, "2026-01-13"),
    ]
    position = replay(trades, {"2026-01-05": 1.5})
    assert position.quantity == 0
    assert position.cost == 0


def test_cannot_sell_more_than_is_held():
    with pytest.raises(InvalidTrades, match="only 10 held"):
        replay([trade("buy", 10, 100.0), trade("sell", 11, 100.0, "2026-01-11")], {})


def test_cannot_sell_before_buying():
    with pytest.raises(InvalidTrades, match="2026-01-05"):
        replay([trade("buy", 10, 100.0), trade("sell", 5, 100.0, "2026-01-05")], {})


def test_trades_are_applied_by_date_not_by_entry_order():
    entered_late = [trade("sell", 5, 150.0, "2026-02-01"), trade("buy", 10, 100.0, "2026-01-01")]
    assert replay(entered_late, {}).realised == pytest.approx(250)


def test_same_day_trades_keep_their_entry_order():
    same_day = [trade("buy", 5, 100.0), trade("sell", 5, 110.0)]
    assert replay(same_day, {}).realised == pytest.approx(50)


def test_split_after_buying_doubles_shares_and_halves_average_cost():
    # 100 at 1,600 cost 160,000. After 2-for-1: 200 shares, still 160,000, 800 each.
    position = replay([trade("buy", 100, 1600.0, "2025-01-01")], {"2025-08-26": 2.0})
    assert position.quantity == 200
    assert position.cost == 160000
    assert position.average_cost == 800


def test_buying_on_the_split_date_is_already_in_new_shares():
    position = replay([trade("buy", 100, 800.0, "2025-08-26")], {"2025-08-26": 2.0})
    assert position.quantity == 100


def test_split_before_the_first_trade_changes_nothing():
    position = replay([trade("buy", 100, 800.0, "2025-09-01")], {"2025-08-26": 2.0})
    assert position.quantity == 100


def test_shares_from_a_split_can_be_sold():
    # 10 at 1,000 becomes 20 at 500. Selling 15 at 600 makes 15 * 100 = 1,500.
    trades = [trade("buy", 10, 1000.0, "2025-01-01"), trade("sell", 15, 600.0, "2025-10-01")]
    position = replay(trades, {"2025-08-26": 2.0})
    assert position.realised == pytest.approx(1500)
    assert position.quantity == 5


def test_splits_apply_in_date_order_between_trades():
    # 10, then x2 = 20, then buy 5 = 25, then x3 = 75.
    trades = [trade("buy", 10, 100.0, "2025-01-01"), trade("buy", 5, 50.0, "2025-06-01")]
    assert replay(trades, {"2025-12-01": 3.0, "2025-03-01": 2.0}).quantity == 75


def test_a_fractional_split_is_supported():
    # A 3-for-2 bonus on 10 shares gives 15.
    assert replay([trade("buy", 10, 100.0, "2025-01-01")], {"2025-03-01": 1.5}).quantity == 15

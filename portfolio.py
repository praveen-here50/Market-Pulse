"""MarketPulse Phase 6: work out holdings by replaying a list of trades.

Nothing here touches the network or a file, so every result can be checked by
hand. Holdings are never stored: they are always recalculated from the trades,
so deleting a mistaken trade corrects everything that depended on it.

Costs use the average cost method. Results leave out brokerage, taxes and
dividends, so they are not your real returns or tax figures.
"""

from dataclasses import dataclass

# A sale may exceed the holding by only this much, to allow for float noise.
QUANTITY_TOLERANCE = 1e-9


class InvalidTrades(Exception):
    """The trades do not make sense, such as selling shares that were not held."""


@dataclass
class Position:
    quantity: float = 0.0
    cost: float = 0.0
    realised: float = 0.0

    @property
    def average_cost(self):
        return self.cost / self.quantity if self.quantity else None

    def split(self, ratio):
        """Multiply the shares. The total paid for them does not change."""
        self.quantity *= ratio

    def buy(self, quantity, price):
        self.quantity += quantity
        self.cost += quantity * price

    def sell(self, quantity, price, date):
        if quantity > self.quantity + QUANTITY_TOLERANCE:
            raise InvalidTrades(
                f"Cannot sell {quantity:g} on {date}: only {self.quantity:g} held then"
            )
        average_cost = self.average_cost
        self.realised += quantity * (price - average_cost)
        self.quantity -= quantity
        self.cost -= quantity * average_cost
        if self.quantity <= QUANTITY_TOLERANCE:
            self.quantity = 0.0
            self.cost = 0.0


def replay(trades, splits):
    """Return one stock's Position after applying its trades and splits by date.

    `splits` maps an ISO date to a ratio: {"2025-08-26": 2.0} means 2 shares for 1.
    Shares bought before that date are doubled. A trade on or after that date is
    already in the new share count, because that is how its price is quoted.

    Trades on the same date stay in the order they were entered.
    """
    position = Position()
    pending_splits = sorted(splits.items())

    for trade in sorted(trades, key=lambda item: item["trade_date"]):
        while pending_splits and pending_splits[0][0] <= trade["trade_date"]:
            position.split(pending_splits.pop(0)[1])

        if trade["side"] == "buy":
            position.buy(trade["quantity"], trade["price"])
        else:
            position.sell(trade["quantity"], trade["price"], trade["trade_date"])

    for _, ratio in pending_splits:
        position.split(ratio)
    return position

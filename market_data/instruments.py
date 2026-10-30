"""The stocks MarketPulse follows and the facts that differ from stock to stock."""

from dataclasses import dataclass
from datetime import time

# Since 3 Aug 2026, F&O stocks stop continuous trading at 15:15 and get their
# closing price from an auction ending at 15:35. Other stocks close at 15:30.
FNO_MARKET_CLOSE = time(15, 35)
NON_FNO_MARKET_CLOSE = time(15, 30)


@dataclass(frozen=True)
class Instrument:
    nse_symbol: str
    is_fno: bool

    @property
    def market_close(self):
        return FNO_MARKET_CLOSE if self.is_fno else NON_FNO_MARKET_CLOSE


# Written by hand, so review it when a stock enters or leaves the F&O segment.
INSTRUMENTS = {
    "RELIANCE.NS": Instrument("RELIANCE", is_fno=True),
    "TCS.NS": Instrument("TCS", is_fno=True),
    "INFY.NS": Instrument("INFY", is_fno=True),
    "HDFCBANK.NS": Instrument("HDFCBANK", is_fno=True),
}


def market_close_for(ticker):
    """Return a stock's closing time. An unknown stock raises KeyError, not a guess."""
    return INSTRUMENTS[ticker].market_close

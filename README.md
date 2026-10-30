# MarketPulse

An Indian stock market intelligence platform, built phase by phase as a
learning and portfolio project. For educational and personal use only. Nothing
here is financial advice.

## Status

| Phase | Scope | State |
| --- | --- | --- |
| 1 | Environment and first market data retrieval | Done |
| 2 | Pandas, financial calculations and data processing | Done |
| 3 to 12 | Everything else in the project plan | Not started |

MarketPulse is still a pair of command-line programs. There is no dashboard,
API, database, automation or AI yet.

## What Phase 1 does

`fetch_prices.py` downloads one month of daily bars for RELIANCE.NS, TCS.NS,
INFY.NS and HDFCBANK.NS, validates them, and prints Open, High, Low, Close,
Volume and the latest available timestamp.

## What Phase 2 does

`analyze_prices.py` downloads one year of daily bars for the same four stocks,
cleans them, and prints a comparison table. `analytics.py` holds the formulas
and never touches the network.

| Metric | Price used | Meaning |
| --- | --- | --- |
| 1D change | Close | Move from the previous close, as shown on charts |
| Price return | Close | Change over the period, without dividends |
| Total return | Adj Close | Change over the period, with dividends |
| Volatility (ann.) | Adj Close | Standard deviation of daily returns, scaled by the square root of 252 |
| Max drawdown | Adj Close | Worst fall from an earlier peak |
| 52W high, 52W low | High, Low | Intraday extremes of the last 52 weeks |
| SMA 20, 50, 200 | Close | Plain mean of the last N closes |
| EMA 20 | Close | Moving average weighted towards recent closes |
| RSI 14 | Close | Wilder's Relative Strength Index, from 0 to 100 |

A metric that cannot be calculated from the data available prints as `n/a`.

## Setup (Command Prompt)

Requires Python 3.12.

```bat
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## Run

```bat
.venv\Scripts\python.exe fetch_prices.py
.venv\Scripts\python.exe analyze_prices.py
.venv\Scripts\python.exe -m pytest
```

Both programs exit with code 0 if every symbol succeeded and 1 otherwise.
The tests use synthetic data and need no network.

## Data disclosure

- Data comes from Yahoo Finance through `yfinance`, an unofficial library. It
  is not an NSE or BSE feed and can change or break without notice.
- These are daily bars, not live quotes. A bar's timestamp is its trading date
  at midnight IST, not the time of the last trade.
- Prices are not adjusted for dividends. Yahoo does adjust them for splits.
- Yahoo sometimes returns placeholder bars with zero volume and a flat price.
  `analyze_prices.py` removes them and says so. `fetch_prices.py` shows raw bars.
- `analyze_prices.py` leaves out today's bar until the session has closed.
- Adj Close values are recalculated by Yahoo after each dividend, so a stored
  Adj Close goes out of date. Returns over a period stay comparable.
- Indicators describe past prices. They are not predictions or advice.
- Check Yahoo's terms before any use beyond personal learning.

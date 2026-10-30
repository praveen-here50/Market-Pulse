# MarketPulse

An Indian stock market intelligence platform, built phase by phase as a
learning and portfolio project. For educational and personal use only. Nothing
here is financial advice.

## Status

| Phase | Scope | State |
| --- | --- | --- |
| 1 | Environment and first market data retrieval | Done |
| 2 to 12 | Everything else in the project plan | Not started |

Only Phase 1 exists today: a command-line program. There is no dashboard, API,
database, automation or AI yet.

## What Phase 1 does

`fetch_prices.py` downloads one month of daily bars for RELIANCE.NS, TCS.NS,
INFY.NS and HDFCBANK.NS, validates them, and prints Open, High, Low, Close,
Volume and the latest available timestamp.

## Setup (Windows PowerShell)

Requires Python 3.12.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## Run

```powershell
.\.venv\Scripts\python.exe fetch_prices.py
.\.venv\Scripts\python.exe -m pytest
```

The program exits with code 0 if every symbol passed validation and 1 otherwise.
The tests use synthetic data and need no network.

## Data disclosure

- Data comes from Yahoo Finance through `yfinance`, an unofficial library. It
  is not an NSE or BSE feed and can change or break without notice.
- These are daily bars, not live quotes. A bar's timestamp is its trading date
  at midnight IST, not the time of the last trade.
- Prices are not adjusted for dividends. Yahoo does adjust them for splits.
- Check Yahoo's terms before any use beyond personal learning.

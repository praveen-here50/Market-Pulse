# MarketPulse

An Indian stock market intelligence platform, built phase by phase as a
learning and portfolio project. For educational and personal use only. Nothing
here is financial advice.

## Status

| Phase | Scope | State |
| --- | --- | --- |
| 1 | Environment and first market data retrieval | Done |
| 2 | Pandas, financial calculations and data processing | Done |
| 3 | Multi-provider market-data architecture | Done |
| 4 | FastAPI backend and API endpoints | Done |
| 5 | Streamlit dashboard and interactive charts | Done |
| 6 | Watchlist and portfolio | Done |
| 7 to 12 | Everything else in the project plan | Not started |

MarketPulse is a set of command-line programs, a local API and a local dashboard.
There is no database, automation or AI yet.

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

## What Phase 3 adds

Programs no longer call Yahoo directly. They ask `market_data`, which tries each
provider in turn and names the source in the output. If a fallback was used, the
output also says what failed first.

| Provider | Data | Limits |
| --- | --- | --- |
| Yahoo through `yfinance` | Daily bars, split-adjusted, with Adj Close | Unofficial. Has been missing at least one real session (18 Mar 2025) |
| NSE bhavcopy files in `data\bhavcopy` | Official end-of-day bars | Files must be downloaded by hand. Not split-adjusted, and no Adj Close |

`analyze_prices.py` needs Adj Close, so it cannot fall back to bhavcopy files and
reports a failure instead of estimating. `fetch_prices.py` can fall back, but
only if the files cover the period without a gap or a corporate action.

### Using bhavcopy files

MarketPulse never downloads from NSE, because NSE's Terms of Use prohibit
automated data collection from its website. Its copyright policy allows
downloads for personal, non-commercial or educational use, so download the
files yourself:

1. On nseindia.com, open the daily reports for the equity market.
2. Download "Full Bhavcopy and Security Deliverable data", named like
   `sec_bhavdata_full_29102026.csv`.
3. Save it in `data\bhavcopy`. This folder is ignored by git, so NSE's data is
   not republished with this code.
4. Compare it with Yahoo:

```bat
.venv\Scripts\python.exe check_providers.py
```

Always trust the date inside a file, not its name: NSE's file named after a
holiday or weekend repeats the previous session.

## What Phase 4 adds

`api.py` serves the same data over HTTP. Start it, then open
http://127.0.0.1:8000/docs to try each endpoint in the browser:

```bat
.venv\Scripts\python.exe -m uvicorn api:app --reload
```

| Endpoint | Returns |
| --- | --- |
| `GET /health` | Whether the server is running. Contacts no provider |
| `GET /stocks` | The stocks we follow and their closing times |
| `GET /stocks/{ticker}/history?period=1mo` | Daily bars. `period` is `1mo` or `1y` |
| `GET /stocks/{ticker}/metrics` | One year of metrics, from finished sessions only |

| Status | Meaning |
| --- | --- |
| 200 | Data follows, with its `source`, `data_type`, `disclaimer` and `notes` |
| 404 | We do not follow that ticker |
| 422 | The request is invalid, such as an unsupported `period` |
| 503 | No provider had usable data. `detail.failures` says why |

Percentages are fractions (0.05 means 5%). A value we cannot calculate is `null`.
The API listens only on this computer and has no login, so do not expose it to a
network. Each data request fetches from Yahoo again, because caching arrives in
Phase 7.

## What Phase 5 adds

`dashboard.py` is a Streamlit page that reads everything from the API. It never
contacts a data provider. Start the API, then the dashboard in a second terminal:

```bat
.venv\Scripts\python.exe -m uvicorn api:app --reload
.venv\Scripts\python.exe -m streamlit run dashboard.py
```

It opens at http://localhost:8501 and shows headline numbers, price with moving
averages, volume, RSI, a table of every plotted value, and a comparison of all
four stocks. It follows your light or dark theme.

- The page stays honest when data is missing: a stopped API, an outage and a
  fallback source without Adj Close each get their own message.
- API answers are kept for 5 minutes, because Streamlit reruns the page on every
  click. A new close can take that long to appear.
- Charts calculate moving averages and RSI from the API's two-decimal prices, so
  a chart value can differ from `/metrics` by about 0.01.

## What Phase 6 adds

The dashboard has Watchlist and Portfolio tabs, backed by new API endpoints.

| Endpoint | Does |
| --- | --- |
| `POST /stocks` | Adds a stock, if a provider has valid data for it |
| `DELETE /stocks/{ticker}` | Removes a stock. Refused while it has trades |
| `GET /trades`, `POST /trades` | Lists or records buys and sells |
| `DELETE /trades/{id}` | Deletes a trade. Refused if a later sale needs its shares |
| `GET /portfolio` | Values every holding at the last finished close |

- Your data stays in `data\user` on this computer. Git ignores it. Back it up
  yourself, because Git will not. Phase 7 replaces these files with a database.
- Holdings are always recalculated from your trades, using the average cost
  method. To correct a mistake, delete the trade and record it again.
- Splits and bonus issues are applied automatically from Yahoo's history.
- If a stock cannot be valued, its row and the portfolio totals show `n/a`, so a
  partial total is never shown as your whole portfolio.
- Quantity must be a whole number of shares. You state whether a stock trades in
  F&O, because closing time depends on it and MarketPulse never reads NSE's list.
- Results leave out brokerage, taxes and dividends, so they are not your real
  returns or tax figures. Nothing here is financial advice.

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
- Bhavcopy data belongs to NSE and is for personal, non-commercial or
  educational use. Commercial use needs a licence from NSE Data.
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

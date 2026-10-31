# MarketPulse

An Indian stock market intelligence platform, built phase by phase as a
learning and portfolio project. For educational and personal use only. Nothing
here is financial advice. It is not affiliated with Yahoo, NSE, Google or Telegram.

## Try the demo

The demo is the real dashboard running on made-up prices. It needs no keys or accounts,
contacts no provider and holds no real data:

```bat
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
run_demo.bat
```

It opens at http://127.0.0.1:8502. Every stock is an invented `DEMO-` company, and real
tickers are refused. What you change is lost when it restarts. The Automation tab shows
the Telegram report and alerts as text, because the demo sends nothing.

## Status

| Phase | Scope | State |
| --- | --- | --- |
| 1 | Environment and first market data retrieval | Done |
| 2 | Pandas, financial calculations and data processing | Done |
| 3 | Multi-provider market-data architecture | Done |
| 4 | FastAPI backend and API endpoints | Done |
| 5 | Streamlit dashboard and interactive charts | Done |
| 6 | Watchlist and portfolio | Done |
| 7 | Database and caching | Done |
| 8 | n8n installation and integration | Done |
| 9 | Telegram automation and scheduled reports | Done |
| 10 | Gemini AI integration | Done |
| 11 | Market analytics, news and alerts | Done |
| 12 | Testing, optimization and deployment | Done |

MarketPulse is a set of command-line programs, a local API, a local dashboard, a
SQLite database, and a local n8n that can send a daily Telegram report with a short
checked note from Gemini.

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
network.

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

- Your data stays in `data\user` on this computer. Git ignores it. See Phase 12 for
  backups.
- Holdings are always recalculated from your trades, using the average cost
  method. To correct a mistake, delete the trade and record it again.
- Splits and bonus issues are applied automatically from Yahoo's history.
- If a stock cannot be valued, its row and the portfolio totals show `n/a`, so a
  partial total is never shown as your whole portfolio.
- Quantity must be a whole number of shares. You state whether a stock trades in
  F&O, because closing time depends on it and MarketPulse never reads NSE's list.
- Results leave out brokerage, taxes and dividends, so they are not your real
  returns or tax figures. Nothing here is financial advice.

## What Phase 7 adds

The watchlist and trades move into a SQLite database, `data\user\marketpulse.db`,
and the API keeps recent downloads there. The endpoints have not changed. SQLite
comes with Python, so there is nothing new to install.

| Table | Holds |
| --- | --- |
| `watchlist` | Followed stocks, in the order they were added |
| `trades` | Every buy and sell. A trade must name a stock on the watchlist |
| `price_downloads` | When each saved download was made and by which provider |
| `price_bars` | The bars of each saved download |

### Your Phase 6 files

The first start imports `watchlist.json` and `trades.json` by itself. It is all or
nothing: a damaged file stops the import with an error and saves nothing. The JSON
files stay in place but are no longer read or updated, so they are only a backup
of your data at the moment of the import. Do not delete `marketpulse.db` to fix
something: the next start would import those old files and lose every later trade.

See Phase 12 for backups.

### Saved prices

The API reuses a download for up to 15 minutes, and the dashboard keeps answers for
5 more, so a price you see can be about 20 minutes older than Yahoo's. These are
daily bars either way, never live prices.

- A saved copy is labelled in `notes`, such as
  `saved copy, downloaded 2026-10-31 09:04 IST`, and the dashboard shows that note.
- A copy made during a session is thrown away once that session closes, so an
  unfinished bar is never reported as the day's close.
- If Yahoo is down and the copy has expired, you get the fallback or an error, not
  old data.
- Fallback answers are not saved, so Yahoo's recovery shows up straight away.
- Splits are never saved, and holdings skip saved prices for 7 days after a split.
  Mixing prices and share counts from either side of a split would misstate a
  holding. So `/portfolio` still asks Yahoo once per stock for its splits.
- `fetch_prices.py`, `analyze_prices.py` and `check_providers.py` always download.

To run a test copy without touching your data, set `MARKETPULSE_DATA_FOLDER`:

```bat
set MARKETPULSE_DATA_FOLDER=%TEMP%\marketpulse-test
.venv\Scripts\python.exe -m uvicorn api:app --port 8010
```

## What Phase 8 adds

`GET /summary` returns every stock's last finished close, both as data and as a
ready-to-send `text`. n8n, a visual automation tool, runs on this computer and calls
it. The report is written in Python, where tests can check it, so n8n only moves it.

```json
{
  "complete": true,
  "stocks": [{"ticker": "SAMPLE.NS", "close": 100.0, "problem": null}],
  "text": "MarketPulse summary, 2026-10-31 09:22 IST\nSAMPLE.NS: 100.00 INR on ..."
}
```

If one stock fails, the others still arrive, that stock gets a `problem`, and
`complete` is `false`. Check `complete` before treating a report as the whole
watchlist.

### Install n8n

Needs Node.js 24 or newer, and about 2.5 GB in `automation\node_modules`, which git
ignores. Nothing is installed globally. `npm ci` installs the exact versions in
`package-lock.json`:

```bat
cd automation
npm ci
cd ..
```

Import the workflow once, then start n8n:

```bat
automation\start_n8n.bat import:workflow --input=workflows\marketpulse_summary.json
automation\start_n8n.bat start
```

1. Start the API in another terminal.
2. Open http://127.0.0.1:5678 about 20 seconds after n8n says it is ready. A "not
   found" page before then only means it is still starting.
3. Create your owner account. It stays on this computer.
4. Open "MarketPulse summary", click Execute Workflow, and read the last node.

If the API is stopped, the run fails with `ECONNREFUSED`. It does not produce an
empty report.

### What to know

- n8n listens only on 127.0.0.1. Keep it that way: `start_n8n.bat` is the only
  supported way to start it, because it also sets that address.
- n8n's data, including its encryption key and a copy of each run's output, is in
  `data\n8n`, which git ignores. Back it up if you add credentials in Phase 9.
- Workflows in `automation\workflows` are public once committed. Never add a real
  token to one: tokens go in n8n's credentials. `tests\test_workflows.py` checks
  every export for secrets and for any address other than `MARKETPULSE_API_URL`.
- MarketPulse never contacts NSE from n8n. See "Using bhavcopy files".
- `npm audit` reports 173 known issues in packages inside n8n 2.45.7, 6 of them
  critical. Do not run `npm audit fix --force`: its "fix" is a downgrade to n8n
  1.17.0. Update by changing the pinned version instead.

## What Phase 9 adds

The "MarketPulse daily report" workflow sends the `/summary` report to Telegram at
16:30 IST, Monday to Friday. It holds prices for your watchlist only. Your holdings
are never sent, because they would leave this computer.

| Situation | What you get |
| --- | --- |
| Normal | The report |
| Some stocks failed | The report, with `INCOMPLETE: 1 of 4 stocks unavailable` at the top |
| Too long for one message | The first stocks, with `N more stocks not shown` |
| API not answering | After 3 tries, an alert with no prices in it |
| Telegram refuses the message | Nothing on Telegram. See n8n's Executions list |
| Computer asleep, or n8n stopped | Nothing, and the missed report is not sent later |

A market holiday on a weekday still sends a report. It repeats the last close with
that session's date, so read the date in each line.

### Set up your bot

1. In Telegram, message `@BotFather`, send `/newbot` and copy the token. Treat it
   like a password: never put it in a file or a chat.
2. Send your new bot any message.
3. Open this in your browser, with your token, and find `"chat":{"id":123456789`:
   `https://api.telegram.org/bot<TOKEN>/getUpdates`
4. Save it in `.env` as `TELEGRAM_CHAT_ID=123456789`.
5. Import the workflow and start n8n:

   ```bat
   automation\start_n8n.bat import:workflow --input=workflows\marketpulse_daily_report.json
   automation\start_n8n.bat start
   ```

6. With the token in `.env` (see Phase 10), load it into n8n's encrypted storage:

   ```bat
   .venv\Scripts\python.exe automation\import_telegram_credential.py
   ```

7. Open "MarketPulse daily report" in n8n. The workflow already names that credential.
8. Start the API, then click Execute Workflow. The report should reach Telegram.
9. Click Publish, so the schedule runs. For it to fire, the computer must be awake
   with the API and n8n both running.

## What Phase 10 adds

`GET /summary?ai=true` adds a short note from Gemini to the report, and the daily
report asks for it. The calculated numbers do not change, and the plain `/summary`
never contacts Gemini.

```text
AI note (Gemini, can be wrong, not advice): SAMPLE.NS changed +1.00% to 100.00 INR...
```

Gemini only rewords your watchlist's prices. `commentary.py` checks every note, and
one failed check drops the whole note:

| Check | Why |
| --- | --- |
| Every number and date must be in the data, with the same sign | A model can invent a figure, or reverse a fall into a rise |
| No advice, predictions or causes | It has no news, so any reason would be a guess |
| No direction words like rose or fell | The signed figure says it, and can be checked |
| Finished answer, 600 characters at most | A note cut off mid-sentence can mislead |

If there is no usable note for any reason, the price report still goes out with a
line such as `AI note unavailable: GEMINI_API_KEY is not set`. The checks are strict
on purpose, so expect some notes to be dropped.

Only watchlist tickers and prices are sent. Your holdings and trades never are. On
Gemini's free tier, Google may use what you send and people may read it, which is
another reason they stay here. Google's terms also say not to rely on it for
financial advice.

### Set up your key

1. Create a key at https://aistudio.google.com/apikey. Treat it like a password.
2. Put it in a file named `.env` in the main folder, which git ignores:

   ```text
   GEMINI_API_KEY=your-key-here
   TELEGRAM_BOT_TOKEN=your-telegram-token-here
   TELEGRAM_CHAT_ID=your-chat-id-here
   ```

3. Start the API, and try it:

   ```bat
   .venv\Scripts\python.exe -m uvicorn api:app --reload
   ```

   Open http://127.0.0.1:8000/summary?ai=true in your browser.

4. Re-import the workflow so n8n uses the new address:

   ```bat
   automation\start_n8n.bat import:workflow --input=workflows\marketpulse_daily_report.json
   ```

The model is `gemini-3.5-flash-lite`. Set `GEMINI_MODEL` to use another.

## What Phase 11 adds

The dashboard has an Insights tab, backed by these endpoints:

| Endpoint | Does |
| --- | --- |
| `GET /analytics` | Counts rises and falls, and ranks the watchlist by 1D change |
| `GET /stocks/{ticker}/news` | Up to 5 recent headlines that name the company |
| `GET /alerts`, `POST /alerts` | Lists or adds alerts |
| `DELETE /alerts/{id}` | Deletes an alert |
| `POST /alerts/check` | Compares alerts with the last finished session |

### Alerts

Add an alert in the Insights tab: a close above or below a level, a 1D move of at least
a percentage in either direction, or RSI 14 above or below a level. The "MarketPulse
alerts" workflow checks them at 16:40 IST on weekdays and sends anything new to Telegram.

- These are levels you choose, not signals, and nothing here is financial advice.
- An alert fires when its condition becomes true. It stays quiet while the condition
  stays true, and can fire again only after the condition has cleared.
- A new alert whose condition is already true fires on the next check.
- If nothing happened, no message is sent, so silence means no alert fired.
- A stock that could not be checked is reported, and its alerts stay ready.
- A stock with alerts cannot be removed until they are deleted.
- If Telegram fails after a check, that alert is not sent again. See n8n's Executions.

To add the workflow to n8n after a fresh install, stop n8n and run:

```bat
automation\start_n8n.bat import:workflow --input=workflows\marketpulse_alerts.json
automation\start_n8n.bat publish:workflow --id=mpAlertsPhase011
```

### News

Headlines come from Yahoo's search and are only shown in the dashboard. They are never
sent to Gemini, because a crafted headline could carry instructions for it.

Coverage is thin. On 31 Oct 2026, Infosys had 5 headlines, M&M had 3 and TCS and IRCTC
had none. No headlines does not mean nothing happened. Yahoo's ticker tags are unreliable,
so a headline must name the company, and related companies can still slip through: M&M's
list included Tech Mahindra.

## What Phase 12 adds

MarketPulse is deployed on this computer, not on the internet. It holds your trades and
has no login, so every part listens only on 127.0.0.1. Putting it online would first
need a login, HTTPS and a hosting account.

### Start everything

```bat
run_marketpulse.bat
```

This backs up the database, then opens the API, dashboard and n8n in minimized windows.
The dashboard is at http://127.0.0.1:8501 and n8n at http://127.0.0.1:5678. Close the
windows to stop them.

To start MarketPulse whenever you log in to Windows, or to stop doing that:

```bat
automation\autostart.bat on
automation\autostart.bat off
```

The scheduled reports need the computer awake at 16:30 and 16:40 IST. Windows must not
be asleep then, and a missed report is not sent later.

### Backups

`run_marketpulse.bat` keeps the last 14 copies in `data\user\backups`. To make one by
hand:

```bat
.venv\Scripts\python.exe backup_data.py
```

These are on the same disk as the database, so a disk failure would lose both. Copy one
somewhere else now and then. To restore, stop MarketPulse and copy a backup over
`data\user\marketpulse.db`. Your `.env` and `data\n8n` are not included.

### Test results

Measured on 31 Oct 2026.

| Check | Result |
| --- | --- |
| Clean install from a fresh export | All tests pass |
| `pip-audit` on `requirements.txt` | No known issues |
| `npm audit` on n8n 2.45.7 | 173 issues inside n8n, 6 critical. No newer stable release |
| Line coverage | 99% |
| `/metrics` from a saved copy | 14 ms |
| `/metrics` after a new download | About 0.9 s |

Saved copies are already fast, so nothing was added for speed. The slow part is waiting
for Yahoo.

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

- The public demo shows only made-up data. Real data stays on the owner's computer.
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

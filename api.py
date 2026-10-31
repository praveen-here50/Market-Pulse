"""MarketPulse API: serve prices, metrics, the watchlist and the portfolio over HTTP.

Run with:  python -m uvicorn api:app --reload
Docs at:   http://127.0.0.1:8000/docs

Every data response names its source and says it is not live. Percentages are
fractions (0.05 means 5%). A value we cannot calculate is null, never a guess.

Endpoints are plain `def`, not `async def`, because yfinance blocks while it
downloads. FastAPI runs plain functions in a thread pool, so one slow download
does not freeze the server.
"""

import html
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Literal

import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

import analytics
import analyze_prices
import fetch_prices
import portfolio
import price_cache
import user_data
from market_data.service import SplitsUnavailable, fetch_splits, fetch_with_fallback

DATA_TYPE = "end_of_day"
DISCLAIMER = (
    "Delayed daily bars, not live exchange prices. Indicators describe past prices "
    "and are not predictions or financial advice."
)

PORTFOLIO_DISCLAIMER = (
    "Valued at the last finished session's close, not a live price. Leaves out "
    "brokerage, taxes and dividends, so these are not your real returns or tax figures."
)

# NSE tickers are letters and digits, and a few also contain & or -, like M&M.NS.
TICKER_PATTERN = r"^[A-Z0-9&-]+\.NS$"

# Asking Yahoo for history from exactly the trade date can return nothing for a
# trade made today, which would look like a failed download.
SPLIT_LOOKBACK = timedelta(days=10)

# A split rewrites past prices, so a saved copy may be in the old share count while
# the split list is already in the new one. Multiplying the two would misstate a
# holding, so holdings skip the saved copy for this long after a split.
RECENT_SPLIT = timedelta(days=7)

# Telegram's limit is 4096 characters. This leaves room for it to count differently.
MAX_REPORT_LENGTH = 4000

PRICE_DIGITS = 2
FRACTION_DIGITS = 6
RSI_DIGITS = 1

app = FastAPI(title="MarketPulse API", version="0.9.0", description=DISCLAIMER)


@app.exception_handler(user_data.Rejected)
@app.exception_handler(portfolio.InvalidTrades)
def conflict(request, error):
    """Turn a request that clashes with saved data into a 409 with the reason."""
    return JSONResponse(status_code=409, content={"detail": str(error)})


class Stock(BaseModel):
    ticker: str
    nse_symbol: str
    is_fno: bool
    market_close: str


class NewStock(BaseModel):
    ticker: str = Field(pattern=TICKER_PATTERN)
    is_fno: bool


class NewTrade(BaseModel):
    ticker: str
    side: Literal["buy", "sell"]
    quantity: int = Field(gt=0)
    price: float = Field(gt=0)
    trade_date: date


class Trade(NewTrade):
    id: str


class Holding(BaseModel):
    ticker: str
    quantity: float | None = None
    average_cost: float | None = None
    invested: float | None = None
    last_close: float | None = None
    last_close_date: date | None = None
    source: str | None = None
    market_value: float | None = None
    unrealised: float | None = None
    unrealised_fraction: float | None = None
    realised: float | None = None
    problem: str | None = None


class PortfolioResponse(BaseModel):
    data_type: str = DATA_TYPE
    disclaimer: str = PORTFOLIO_DISCLAIMER
    holdings: list[Holding]
    total_invested: float | None
    total_market_value: float | None
    total_unrealised: float | None
    total_realised: float | None


class Bar(BaseModel):
    date: date
    open: float
    high: float
    low: float
    close: float
    adj_close: float | None
    volume: int


class DataResponse(BaseModel):
    ticker: str
    source: str
    data_type: str = DATA_TYPE
    disclaimer: str = DISCLAIMER
    notes: list[str]


class HistoryResponse(DataResponse):
    latest_bar_status: str
    latest_bar_in_progress: bool
    bars: list[Bar]


class MetricsResponse(DataResponse):
    bars_used: int
    first_bar: date
    last_bar: date
    close: float
    change_1d: float | None
    price_return: float | None
    total_return: float | None
    volatility_annualised: float | None
    max_drawdown: float | None
    high_52w: float | None
    low_52w: float | None
    sma_20: float | None
    sma_50: float | None
    sma_200: float | None
    ema_20: float | None
    rsi_14: float | None


class StockSummary(BaseModel):
    ticker: str
    source: str | None = None
    last_bar: date | None = None
    close: float | None = None
    change_1d: float | None = None
    rsi_14: float | None = None
    notes: list[str] = []
    problem: str | None = None


class SummaryResponse(BaseModel):
    data_type: str = DATA_TYPE
    disclaimer: str = DISCLAIMER
    generated_at: datetime
    complete: bool
    stocks: list[StockSummary]
    text: str
    text_html: str


def rounded(value, digits):
    """Return a plain float for JSON, or None for NaN, which JSON cannot carry."""
    return None if pd.isna(value) else round(float(value), digits)


def require_known_ticker(ticker):
    """Return a followed stock. Stop here for others, without asking any provider."""
    instrument = user_data.load_watchlist().get(ticker)
    if instrument is None:
        raise HTTPException(status_code=404, detail=f"Unknown ticker: {ticker}")
    return instrument


def data_unavailable(ticker, failures):
    """Return the error for when no provider could supply usable data."""
    return HTTPException(
        status_code=503,
        detail={"message": f"No usable data for {ticker}", "failures": failures},
    )


def load_clean_bars(ticker, period, check, now, market_close, use_saved=True):
    """Return (clean bars, source, notes on placeholders, fallbacks and saved copies)."""
    result = price_cache.fetch(ticker, period, check, now, market_close, use_saved)
    if result.history is None:
        raise data_unavailable(ticker, result.failures)

    cleaned, removed = analytics.remove_placeholder_bars(result.history)
    if cleaned.empty:
        raise data_unavailable(ticker, ["no real bars left after cleaning"])

    notes = [f"fallback used because {failure}" for failure in result.failures]
    if result.downloaded_at is not None:
        notes.append(f"saved copy, downloaded {result.downloaded_at:%Y-%m-%d %H:%M} IST")
    if len(removed) > 0:
        dates = ", ".join(f"{day:%Y-%m-%d}" for day in removed)
        notes.append(f"removed {len(removed)} zero-volume placeholder bar(s): {dates}")
    return cleaned, result.source, notes


def to_bar(day, row):
    return Bar(
        date=day.date(),
        open=rounded(row["Open"], PRICE_DIGITS),
        high=rounded(row["High"], PRICE_DIGITS),
        low=rounded(row["Low"], PRICE_DIGITS),
        close=rounded(row["Close"], PRICE_DIGITS),
        # NSE bhavcopy files have no Adj Close.
        adj_close=rounded(row.get("Adj Close"), PRICE_DIGITS),
        volume=int(row["Volume"]),
    )


@app.get("/health")
def health():
    """Say the server is running. This does not contact any data provider."""
    return {"status": "ok"}


@app.get("/stocks")
def list_stocks() -> list[Stock]:
    """List the stocks on the watchlist."""
    return [
        Stock(
            ticker=ticker,
            nse_symbol=instrument.nse_symbol,
            is_fno=instrument.is_fno,
            market_close=f"{instrument.market_close:%H:%M}",
        )
        for ticker, instrument in user_data.load_watchlist().items()
    ]


@app.post("/stocks", status_code=201)
def add_stock(stock: NewStock) -> NewStock:
    """Add a stock to the watchlist, if a provider has valid data for it."""
    now = pd.Timestamp.now(tz=fetch_prices.MARKET_TIMEZONE)
    result = fetch_with_fallback(
        stock.ticker, fetch_prices.PERIOD, lambda table: fetch_prices.validate_history(table, now)
    )
    if result.history is None:
        raise HTTPException(
            status_code=422,
            detail=f"No valid data for {stock.ticker}: {'; '.join(result.failures)}",
        )
    user_data.add_stock(stock.ticker, stock.is_fno)
    return stock


@app.delete("/stocks/{ticker}", status_code=204)
def remove_stock(ticker: str):
    """Remove a stock from the watchlist. Stocks that have trades are refused."""
    require_known_ticker(ticker)
    user_data.remove_stock(ticker)


@app.get("/stocks/{ticker}/history")
def get_history(ticker: str, period: Literal["1mo", "1y"] = "1mo") -> HistoryResponse:
    """Return daily bars. Today's bar stays in during the session, marked by status."""
    market_close = require_known_ticker(ticker).market_close
    now = pd.Timestamp.now(tz=fetch_prices.MARKET_TIMEZONE)

    bars, source, notes = load_clean_bars(
        ticker, period, lambda table: fetch_prices.validate_history(table, now), now, market_close
    )
    return HistoryResponse(
        ticker=ticker,
        source=source,
        notes=notes,
        latest_bar_status=fetch_prices.describe_latest_bar(bars.index[-1], now, market_close),
        latest_bar_in_progress=fetch_prices.is_bar_in_progress(bars.index[-1], now, market_close),
        bars=[to_bar(day, row) for day, row in bars.iterrows()],
    )


@app.get("/stocks/{ticker}/metrics")
def get_metrics(ticker: str) -> MetricsResponse:
    """Return one year of metrics, calculated from finished sessions only."""
    market_close = require_known_ticker(ticker).market_close
    now = pd.Timestamp.now(tz=fetch_prices.MARKET_TIMEZONE)

    bars, source, notes = load_clean_bars(
        ticker,
        analyze_prices.ANALYSIS_PERIOD,
        lambda table: analyze_prices.validate_for_analysis(table, now),
        now,
        market_close,
    )
    # Placeholders are already gone, so this only leaves out an unfinished bar.
    finished, unfinished_notes = analyze_prices.prepare_history(bars, now, market_close)
    if finished.empty:
        raise data_unavailable(ticker, ["no finished sessions yet"])

    summary = analytics.summarize(finished)
    return MetricsResponse(
        ticker=ticker,
        source=source,
        notes=notes + unfinished_notes,
        bars_used=summary["Bars used"],
        first_bar=summary["First bar"].date(),
        last_bar=summary["Last bar"].date(),
        close=rounded(summary["Close"], PRICE_DIGITS),
        change_1d=rounded(summary["1D change"], FRACTION_DIGITS),
        price_return=rounded(summary["Price return"], FRACTION_DIGITS),
        total_return=rounded(summary["Total return"], FRACTION_DIGITS),
        volatility_annualised=rounded(summary["Volatility (ann.)"], FRACTION_DIGITS),
        max_drawdown=rounded(summary["Max drawdown"], FRACTION_DIGITS),
        high_52w=rounded(summary["52W high"], PRICE_DIGITS),
        low_52w=rounded(summary["52W low"], PRICE_DIGITS),
        sma_20=rounded(summary["SMA 20"], PRICE_DIGITS),
        sma_50=rounded(summary["SMA 50"], PRICE_DIGITS),
        sma_200=rounded(summary["SMA 200"], PRICE_DIGITS),
        ema_20=rounded(summary["EMA 20"], PRICE_DIGITS),
        rsi_14=rounded(summary["RSI 14"], RSI_DIGITS),
    )


def summarize_stock(ticker):
    """Return one stock's headline numbers. A failure gives a reason, not a guess."""
    try:
        metrics = get_metrics(ticker)
    except HTTPException as error:
        return StockSummary(ticker=ticker, problem="; ".join(error.detail["failures"]))
    return StockSummary(
        ticker=ticker,
        source=metrics.source,
        last_bar=metrics.last_bar,
        close=metrics.close,
        change_1d=metrics.change_1d,
        rsi_14=metrics.rsi_14,
        notes=metrics.notes,
    )


def summary_line(stock):
    if stock.problem:
        return f"{stock.ticker}: unavailable ({stock.problem})"
    change = "n/a" if stock.change_1d is None else f"{stock.change_1d:+.2%}"
    rsi = "n/a" if stock.rsi_14 is None else f"{stock.rsi_14:.1f}"
    return f"{stock.ticker}: {stock.close:,.2f} INR on {stock.last_bar}, 1D {change}, RSI {rsi}"


def summary_text(stocks, generated_at):
    """Write the report automations send on, so its wording is tested here.

    The header and footer always fit. If the stocks do not, the last ones are left
    out and the report says how many, because Telegram refuses a message too long.
    """
    sources = sorted({stock.source for stock in stocks if stock.source})
    missing = sum(1 for stock in stocks if stock.problem)

    header = [f"MarketPulse summary, {generated_at:%Y-%m-%d %H:%M} IST"]
    if missing:
        header.append(f"INCOMPLETE: {missing} of {len(stocks)} stocks unavailable")
    footer = [f"Source: {', '.join(sources) or 'none available'}", DISCLAIMER]

    lines = [summary_line(stock) for stock in stocks]
    shown = len(lines)
    while True:
        cut = [f"{len(lines) - shown} more stocks not shown"] if shown < len(lines) else []
        text = "\n".join([*header, *lines[:shown], *cut, *footer])
        if len(text) <= MAX_REPORT_LENGTH:
            return text
        shown -= 1


@app.get("/summary")
def get_summary() -> SummaryResponse:
    """Return every stock's last finished close, as data and as ready-to-send text.

    One stock failing does not fail the rest, so check `complete` before treating
    this as the whole watchlist.
    """
    now = pd.Timestamp.now(tz=fetch_prices.MARKET_TIMEZONE)
    stocks = [summarize_stock(ticker) for ticker in user_data.load_watchlist()]
    text = summary_text(stocks, now)
    return SummaryResponse(
        generated_at=now,
        complete=not any(stock.problem for stock in stocks),
        stocks=stocks,
        text=text,
        # Telegram measures length after reading these codes, so escaping is safe.
        text_html=html.escape(text, quote=False),
    )


def splits_for(ticker, trades):
    """Return the splits since a stock's first trade, or raise SplitsUnavailable."""
    first_trade = min(pd.Timestamp(trade["trade_date"]) for trade in trades).date()
    return fetch_splits(ticker, (first_trade - SPLIT_LOOKBACK).isoformat())


def require_valid_replay(ticker, trades):
    """Return a check that refuses a trade list which does not replay cleanly."""
    remaining = [trade for trade in trades if trade["ticker"] == ticker]
    if not remaining:
        return lambda updated: None

    try:
        splits = splits_for(ticker, remaining)
    except SplitsUnavailable as error:
        raise data_unavailable(ticker, [str(error)]) from error

    def check(updated):
        portfolio.replay([trade for trade in updated if trade["ticker"] == ticker], splits)

    return check


@app.get("/trades")
def list_trades() -> list[Trade]:
    """List every recorded trade, oldest first."""
    return sorted(user_data.load_trades(), key=lambda trade: trade["trade_date"])


@app.post("/trades", status_code=201)
def add_trade(trade: NewTrade) -> Trade:
    """Record a trade. A sale needs split history, to know how many shares were held."""
    require_known_ticker(trade.ticker)
    today = pd.Timestamp.now(tz=fetch_prices.MARKET_TIMEZONE).date()
    if trade.trade_date > today:
        raise HTTPException(status_code=422, detail="Trade date cannot be in the future")

    entry = {**trade.model_dump(), "trade_date": trade.trade_date.isoformat()}
    check = lambda updated: None
    if trade.side == "sell":
        check = require_valid_replay(trade.ticker, [*user_data.load_trades(), entry])
    return user_data.add_trade(entry, check)


@app.delete("/trades/{trade_id}", status_code=204)
def delete_trade(trade_id: str):
    """Delete a trade, unless a later sale depends on the shares it bought."""
    trades = user_data.load_trades()
    trade = next((item for item in trades if item["id"] == trade_id), None)
    if trade is None:
        raise HTTPException(status_code=404, detail=f"Unknown trade: {trade_id}")

    check = require_valid_replay(trade["ticker"], trades)
    user_data.delete_trade(trade_id, check)


def has_recent_split(splits, now):
    return any(now.date() - date.fromisoformat(day) <= RECENT_SPLIT for day in splits)


def latest_finished_close(ticker, instrument, now, use_saved):
    """Return (close, date, source) of the last finished session, or raise 503."""
    bars, source, _ = load_clean_bars(
        ticker,
        fetch_prices.PERIOD,
        lambda table: fetch_prices.validate_history(table, now),
        now,
        instrument.market_close,
        use_saved,
    )
    finished, _ = analyze_prices.prepare_history(bars, now, instrument.market_close)
    if finished.empty:
        raise data_unavailable(ticker, ["no finished sessions yet"])
    return float(finished["Close"].iloc[-1]), finished.index[-1].date(), source


def value_holding(ticker, instrument, trades, now):
    """Return one stock's holding. A missing input gives nulls and a reason, not a guess."""
    try:
        splits = splits_for(ticker, trades)
        position = portfolio.replay(trades, splits)
        holding = Holding(
            ticker=ticker,
            quantity=rounded(position.quantity, FRACTION_DIGITS),
            average_cost=rounded(position.average_cost, PRICE_DIGITS),
            invested=rounded(position.cost, PRICE_DIGITS),
            realised=rounded(position.realised, PRICE_DIGITS),
        )
        if position.quantity == 0:
            holding.market_value = 0.0
            holding.unrealised = 0.0
            return holding

        close, close_date, source = latest_finished_close(
            ticker, instrument, now, use_saved=not has_recent_split(splits, now)
        )
    except SplitsUnavailable as error:
        return Holding(ticker=ticker, problem=str(error))
    except HTTPException as error:
        return Holding(ticker=ticker, problem="; ".join(error.detail["failures"]))

    market_value = position.quantity * close
    holding.last_close = rounded(close, PRICE_DIGITS)
    holding.last_close_date = close_date
    holding.source = source
    holding.market_value = rounded(market_value, PRICE_DIGITS)
    holding.unrealised = rounded(market_value - position.cost, PRICE_DIGITS)
    holding.unrealised_fraction = rounded(market_value / position.cost - 1, FRACTION_DIGITS)
    return holding


def total(holdings, field):
    """Add up a field. One unknown holding makes the total unknown, not smaller."""
    values = [getattr(holding, field) for holding in holdings]
    if any(value is None for value in values):
        return None
    return round(sum(values), PRICE_DIGITS)


@app.get("/portfolio")
def get_portfolio() -> PortfolioResponse:
    """Return every holding, valued at the last finished session's close."""
    now = pd.Timestamp.now(tz=fetch_prices.MARKET_TIMEZONE)
    watchlist = user_data.load_watchlist()

    trades_by_ticker = defaultdict(list)
    for trade in user_data.load_trades():
        trades_by_ticker[trade["ticker"]].append(trade)

    holdings = [
        value_holding(ticker, watchlist[ticker], trades, now)
        for ticker, trades in trades_by_ticker.items()
    ]
    return PortfolioResponse(
        holdings=holdings,
        total_invested=total(holdings, "invested"),
        total_market_value=total(holdings, "market_value"),
        total_unrealised=total(holdings, "unrealised"),
        total_realised=total(holdings, "realised"),
    )

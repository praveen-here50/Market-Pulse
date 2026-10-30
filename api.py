"""MarketPulse Phase 4: serve prices and metrics over HTTP.

Run with:  python -m uvicorn api:app --reload
Docs at:   http://127.0.0.1:8000/docs

Every data response names its source and says it is not live. Percentages are
fractions (0.05 means 5%). A value we cannot calculate is null, never a guess.

Endpoints are plain `def`, not `async def`, because yfinance blocks while it
downloads. FastAPI runs plain functions in a thread pool, so one slow download
does not freeze the server.
"""

from datetime import date
from typing import Literal

import pandas as pd
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

import analytics
import analyze_prices
import fetch_prices
from market_data.instruments import INSTRUMENTS, market_close_for
from market_data.service import fetch_with_fallback

DATA_TYPE = "end_of_day"
DISCLAIMER = (
    "Delayed daily bars, not live exchange prices. Indicators describe past prices "
    "and are not predictions or financial advice."
)

PRICE_DIGITS = 2
FRACTION_DIGITS = 6
RSI_DIGITS = 1

app = FastAPI(title="MarketPulse API", version="0.4.0", description=DISCLAIMER)


class Stock(BaseModel):
    ticker: str
    nse_symbol: str
    is_fno: bool
    market_close: str


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


def rounded(value, digits):
    """Return a plain float for JSON, or None for NaN, which JSON cannot carry."""
    return None if pd.isna(value) else round(float(value), digits)


def require_known_ticker(ticker):
    """Stop here for stocks we do not follow, without asking any provider."""
    if ticker not in INSTRUMENTS:
        raise HTTPException(status_code=404, detail=f"Unknown ticker: {ticker}")


def data_unavailable(ticker, failures):
    """Return the error for when no provider could supply usable data."""
    return HTTPException(
        status_code=503,
        detail={"message": f"No usable data for {ticker}", "failures": failures},
    )


def load_clean_bars(ticker, period, check):
    """Return (clean bars, source, placeholder notes and fallback notes)."""
    result = fetch_with_fallback(ticker, period, check)
    if result.history is None:
        raise data_unavailable(ticker, result.failures)

    cleaned, removed = analytics.remove_placeholder_bars(result.history)
    if cleaned.empty:
        raise data_unavailable(ticker, ["no real bars left after cleaning"])

    notes = [f"fallback used because {failure}" for failure in result.failures]
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
    """List the stocks MarketPulse follows."""
    return [
        Stock(
            ticker=ticker,
            nse_symbol=instrument.nse_symbol,
            is_fno=instrument.is_fno,
            market_close=f"{instrument.market_close:%H:%M}",
        )
        for ticker, instrument in INSTRUMENTS.items()
    ]


@app.get("/stocks/{ticker}/history")
def get_history(ticker: str, period: Literal["1mo", "1y"] = "1mo") -> HistoryResponse:
    """Return daily bars. Today's bar stays in during the session, marked by status."""
    require_known_ticker(ticker)
    now = pd.Timestamp.now(tz=fetch_prices.MARKET_TIMEZONE)

    bars, source, notes = load_clean_bars(
        ticker, period, lambda table: fetch_prices.validate_history(table, now)
    )
    return HistoryResponse(
        ticker=ticker,
        source=source,
        notes=notes,
        latest_bar_status=fetch_prices.describe_latest_bar(
            bars.index[-1], now, market_close_for(ticker)
        ),
        bars=[to_bar(day, row) for day, row in bars.iterrows()],
    )


@app.get("/stocks/{ticker}/metrics")
def get_metrics(ticker: str) -> MetricsResponse:
    """Return one year of metrics, calculated from finished sessions only."""
    require_known_ticker(ticker)
    now = pd.Timestamp.now(tz=fetch_prices.MARKET_TIMEZONE)

    bars, source, notes = load_clean_bars(
        ticker,
        analyze_prices.ANALYSIS_PERIOD,
        lambda table: analyze_prices.validate_for_analysis(table, now),
    )
    # Placeholders are already gone, so this only leaves out an unfinished bar.
    finished, unfinished_notes = analyze_prices.prepare_history(
        bars, now, market_close_for(ticker)
    )
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

"""MarketPulse Phase 5: a Streamlit dashboard that reads from the local API.

Start the API first, then in a second terminal:
    python -m streamlit run dashboard.py

This page calculates no prices of its own and never contacts a data provider.
"""

import streamlit as st

import dashboard_support as support

# Streamlit reruns this whole script on every click. Without this cache, each
# click would make the API download from Yahoo again. Errors are not cached.
CACHE_SECONDS = 300

START_API_COMMAND = r".venv\Scripts\python.exe -m uvicorn api:app --reload"


@st.cache_data(ttl=CACHE_SECONDS, show_spinner="Loading from the MarketPulse API...")
def load(path):
    return support.fetch_json(path)


def show_stat_tiles(metrics):
    """Show the headline numbers, with no good or bad coloring on any of them."""
    tiles = [
        ("Close", support.format_price(metrics["close"])),
        ("1D change", support.format_percent(metrics["change_1d"])),
        ("Total return (1Y)", support.format_percent(metrics["total_return"])),
        ("Volatility (ann.)", support.format_unsigned_percent(metrics["volatility_annualised"])),
        ("Max drawdown", support.format_percent(metrics["max_drawdown"])),
        ("RSI 14", support.format_rsi(metrics["rsi_14"])),
    ]
    for column, (label, value) in zip(st.columns(len(tiles)), tiles):
        column.metric(label, value)


def show_stock(ticker, view, theme):
    """Show one stock. Data that is missing is explained, not filled in."""
    try:
        history = load(f"/stocks/{ticker}/history?period=1y")
    except support.DataUnavailable as error:
        st.warning(f"No usable price data for {ticker}.")
        for failure in error.failures:
            st.caption(failure)
        return

    last_bar = history["bars"][-1]["date"]
    st.caption(f"Source: {history['source']} | Last bar: {last_bar} | {history['latest_bar_status']}")
    if history["latest_bar_in_progress"]:
        st.warning("Today's session has not closed. Its bar is shown but left out of indicators.")

    try:
        metrics = load(f"/stocks/{ticker}/metrics")
    except support.DataUnavailable as error:
        st.warning("Metrics are unavailable, so only prices are shown.")
        for failure in error.failures:
            st.caption(failure)
    else:
        show_stat_tiles(metrics)

    for note in history["notes"]:
        st.caption(f"Note: {note}")

    full_history = support.bars_to_frame(history["bars"])
    frame = support.add_indicators(full_history, history["latest_bar_in_progress"])
    frame = support.crop_to_view(frame, view)

    st.subheader("Price and moving averages")
    st.plotly_chart(support.price_chart(frame, theme), theme=None, width="stretch")

    volume_column, rsi_column = st.columns(2)
    with volume_column:
        st.subheader("Volume")
        st.plotly_chart(support.volume_chart(frame, theme), theme=None, width="stretch")
    with rsi_column:
        st.subheader("RSI 14")
        st.plotly_chart(support.rsi_chart(frame, theme), theme=None, width="stretch")
        st.caption("30 and 70 are conventional reference levels, not buy or sell signals.")

    with st.expander("Table view"):
        st.dataframe(support.table_view(frame), width="stretch")


def show_comparison(stocks):
    """Compare every stock that has metrics, and name any that does not."""
    st.subheader("All stocks")
    metrics_by_ticker = {}
    for stock in stocks:
        ticker = stock["ticker"]
        try:
            metrics_by_ticker[ticker] = load(f"/stocks/{ticker}/metrics")
        except support.DataUnavailable:
            st.warning(f"No metrics for {ticker}.")

    if metrics_by_ticker:
        table = support.comparison_table(metrics_by_ticker)
        st.dataframe(table, height=support.full_table_height(table), width="stretch")


def main():
    st.set_page_config(page_title="MarketPulse", layout="wide")
    st.title("MarketPulse")
    st.info(
        "Delayed daily bars, not live exchange prices. Indicators describe past "
        "prices and are not predictions or financial advice."
    )

    try:
        stocks = load("/stocks")
        tickers = [stock["ticker"] for stock in stocks]

        stock_column, view_column = st.columns([2, 3])
        ticker = stock_column.selectbox("Stock", tickers)
        view = view_column.radio("Chart range", list(support.VIEWS), index=2, horizontal=True)

        theme = st.context.theme.type or "light"
        show_stock(ticker, view, theme)
        show_comparison(stocks)
    except support.ApiNotRunning:
        st.error("The MarketPulse API is not running. Start it in another terminal:")
        st.code(START_API_COMMAND, language="bat")


if __name__ == "__main__":
    main()

"""MarketPulse: a Streamlit dashboard that reads from the local API.

Start the API first, then in a second terminal:
    python -m streamlit run dashboard.py

This page calculates no prices of its own and never contacts a data provider.
"""

from datetime import date

import streamlit as st

import dashboard_support as support

# Streamlit reruns this whole script on every click. Without this cache, each
# click would make the API download from Yahoo again. Errors are not cached.
CACHE_SECONDS = 300

START_API_COMMAND = r".venv\Scripts\python.exe -m uvicorn api:app --reload"


@st.cache_data(ttl=CACHE_SECONDS, show_spinner="Loading from the MarketPulse API...")
def load(path):
    return support.fetch_json(path)


# A cached function must not hold on to a valuation after the trades change, so
# saving a trade clears this one. Prices in `load` are not affected by trades.
@st.cache_data(ttl=CACHE_SECONDS, show_spinner="Valuing the portfolio...")
def load_portfolio():
    return support.fetch_json("/portfolio")


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


def apply_change(method, path, body=None):
    """Send a change. Refresh the page if it worked, or show why it was refused."""
    try:
        support.send_json(method, path, body)
    except support.RequestRejected as error:
        st.error(str(error))
    except support.DataUnavailable as error:
        st.error("Not saved, because market data is unavailable right now.")
        for failure in error.failures:
            st.caption(failure)
    else:
        load_portfolio.clear()
        st.rerun()


def show_watchlist(stocks):
    """Show the followed stocks, with forms to add and remove them."""
    st.dataframe(support.watchlist_table(stocks), width="stretch")

    with st.form("add_stock", clear_on_submit=True):
        st.subheader("Add a stock")
        ticker = st.text_input("NSE ticker", placeholder="IRCTC.NS")
        is_fno = st.checkbox(
            "This stock trades in F&O",
            help="Closing time depends on this: 15:35 for F&O stocks, 15:30 for others.",
        )
        if st.form_submit_button("Add to watchlist") and ticker:
            apply_change("POST", "/stocks", {"ticker": ticker.strip().upper(), "is_fno": is_fno})

    with st.form("remove_stock"):
        st.subheader("Remove a stock")
        ticker = st.selectbox("Stock to remove", [stock["ticker"] for stock in stocks])
        if st.form_submit_button("Remove from watchlist"):
            apply_change("DELETE", f"/stocks/{ticker}")


def show_portfolio_summary(portfolio):
    """Show the totals and holdings. Any unknown value is called out, not summed around."""
    tiles = [
        ("Invested", support.format_price(portfolio["total_invested"])),
        ("Market value", support.format_price(portfolio["total_market_value"])),
        ("Unrealised P&L", support.format_signed_price(portfolio["total_unrealised"])),
        ("Realised P&L", support.format_signed_price(portfolio["total_realised"])),
    ]
    for column, (label, value) in zip(st.columns(len(tiles)), tiles):
        column.metric(label, value)

    table = support.holdings_table(portfolio["holdings"])
    st.dataframe(table, height=support.full_table_height(table), width="stretch")

    for holding in portfolio["holdings"]:
        if holding["problem"]:
            st.warning(f"{holding['ticker']} could not be valued, so totals are n/a.")
            st.caption(holding["problem"])


def show_portfolio(stocks):
    """Show holdings and trades, with forms to record and delete trades."""
    portfolio = load_portfolio()
    st.info(portfolio["disclaimer"])
    trades = support.fetch_json("/trades")

    if portfolio["holdings"]:
        show_portfolio_summary(portfolio)
    else:
        st.write("No trades recorded yet. Add your first one below.")

    with st.form("add_trade", clear_on_submit=True):
        st.subheader("Record a trade")
        ticker_column, side_column = st.columns(2)
        ticker = ticker_column.selectbox("Stock", [stock["ticker"] for stock in stocks])
        side = side_column.radio("Side", ["buy", "sell"], horizontal=True)

        quantity_column, price_column, date_column = st.columns(3)
        quantity = quantity_column.number_input("Quantity", min_value=1, step=1)
        price = price_column.number_input("Price per share (₹)", min_value=0.01, format="%.2f")
        trade_date = date_column.date_input("Trade date", max_value=date.today())

        if st.form_submit_button("Save trade"):
            apply_change(
                "POST",
                "/trades",
                {
                    "ticker": ticker,
                    "side": side,
                    "quantity": quantity,
                    "price": price,
                    "trade_date": trade_date.isoformat(),
                },
            )

    if trades:
        st.subheader("Trades")
        st.dataframe(support.trades_table(trades), width="stretch")

        with st.form("delete_trade"):
            labels = {support.trade_label(trade): trade["id"] for trade in trades}
            label = st.selectbox("Trade to delete", list(labels))
            if st.form_submit_button("Delete trade"):
                apply_change("DELETE", f"/trades/{labels[label]}")


def main():
    st.set_page_config(page_title="MarketPulse", layout="wide")
    st.title("MarketPulse")
    st.info(
        "Delayed daily bars, not live exchange prices. Indicators describe past "
        "prices and are not predictions or financial advice."
    )

    try:
        stocks = support.fetch_json("/stocks")
        tickers = [stock["ticker"] for stock in stocks]
        market_tab, watchlist_tab, portfolio_tab = st.tabs(["Market", "Watchlist", "Portfolio"])

        with market_tab:
            stock_column, view_column = st.columns([2, 3])
            ticker = stock_column.selectbox("Stock", tickers)
            view = view_column.radio("Chart range", list(support.VIEWS), index=2, horizontal=True)

            theme = st.context.theme.type or "light"
            show_stock(ticker, view, theme)
            show_comparison(stocks)

        with watchlist_tab:
            show_watchlist(stocks)

        with portfolio_tab:
            show_portfolio(stocks)
    except support.ApiNotRunning:
        st.error("The MarketPulse API is not running. Start it in another terminal:")
        st.code(START_API_COMMAND, language="bat")


if __name__ == "__main__":
    main()

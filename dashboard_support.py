"""MarketPulse: the parts of the dashboard that do not need Streamlit.

This covers calling the API, formatting values and building charts, so all of
it can be tested without a browser. dashboard.py only lays the page out.
"""

import os

import httpx
import pandas as pd
import plotly.graph_objects as go

import analytics

API_URL = os.environ.get("MARKETPULSE_API_URL", "http://127.0.0.1:8000")
REQUEST_TIMEOUT_SECONDS = 60
MISSING = "n/a"

# The public demo replaces these. See demo.py.
client = httpx
DEMO_NOTICE = None

ALERT_KINDS = {
    "close_above": "Close above",
    "close_below": "Close below",
    "move_at_least": "1D move of at least (%)",
    "rsi_above": "RSI 14 above",
    "rsi_below": "RSI 14 below",
}

VIEWS = {
    "1 month": pd.DateOffset(months=1),
    "6 months": pd.DateOffset(months=6),
    "1 year": pd.DateOffset(years=1),
}

# RSI 30 and 70 are conventional reference levels, not buy or sell signals.
RSI_REFERENCE_LEVELS = (30, 70)

# Series colors were checked with the dataviz palette validator against
# Streamlit's own light and dark backgrounds. Aqua and yellow are below 3:1
# contrast in light mode, so the page must keep its direct labels and table view.
THEMES = {
    "light": {
        "series": ("#2a78d6", "#eb6834", "#1baf7a", "#eda100"),
        "text": "#52514e",
        "muted": "#898781",
        "grid": "#e1e0d9",
        "axis": "#c3c2b7",
    },
    "dark": {
        "series": ("#3987e5", "#d95926", "#199e70", "#c98500"),
        "text": "#c3c2b7",
        "muted": "#898781",
        "grid": "#2c2c2a",
        "axis": "#383835",
    },
}

LINE_WIDTH = 2
RIGHT_MARGIN_FOR_LABELS = 72
TABLE_ROW_HEIGHT = 35
PRICE_SERIES = {"close": "Close", "sma_20": "SMA 20", "sma_50": "SMA 50", "sma_200": "SMA 200"}

# End labels closer together than this share of the chart's height would touch.
MIN_LABEL_GAP = 0.06

COMPARISON_ROWS = {
    "close": ("Close", "price"),
    "change_1d": ("1D change", "percent"),
    "price_return": ("Price return", "percent"),
    "total_return": ("Total return", "percent"),
    "volatility_annualised": ("Volatility (ann.)", "unsigned_percent"),
    "max_drawdown": ("Max drawdown", "percent"),
    "high_52w": ("52W high", "price"),
    "low_52w": ("52W low", "price"),
    "sma_20": ("SMA 20", "price"),
    "sma_50": ("SMA 50", "price"),
    "sma_200": ("SMA 200", "price"),
    "ema_20": ("EMA 20", "price"),
    "rsi_14": ("RSI 14", "rsi"),
}


class ApiNotRunning(Exception):
    """The dashboard could not reach the API at all."""


class DataUnavailable(Exception):
    """The API is running, but no provider had usable data."""

    def __init__(self, failures):
        super().__init__("; ".join(failures))
        self.failures = failures


class RequestRejected(Exception):
    """The API understood the request and refused it. The message says why."""


def rejection_message(response):
    """Return the API's reason. Validation errors arrive as a list of details."""
    detail = response.json()["detail"]
    if isinstance(detail, list):
        return "; ".join(item["msg"] for item in detail)
    return str(detail)


def send_json(method, path, body=None):
    """Send a change to the API. Return its JSON answer, or None if it has none."""
    try:
        response = client.request(
            method, f"{API_URL}{path}", json=body, timeout=REQUEST_TIMEOUT_SECONDS
        )
    except httpx.TransportError as error:
        raise ApiNotRunning(str(error)) from error

    if response.status_code == 503:
        raise DataUnavailable(response.json()["detail"]["failures"])
    if response.status_code in (404, 409, 422):
        raise RequestRejected(rejection_message(response))
    response.raise_for_status()
    return response.json() if response.content else None


def fetch_json(path):
    """Return the API's JSON answer for a path, or raise one of the errors above."""
    try:
        response = client.get(f"{API_URL}{path}", timeout=REQUEST_TIMEOUT_SECONDS)
    except httpx.TransportError as error:
        raise ApiNotRunning(str(error)) from error

    if response.status_code == 503:
        raise DataUnavailable(response.json()["detail"]["failures"])
    response.raise_for_status()
    return response.json()


def format_price(value):
    return MISSING if value is None else f"₹{value:,.2f}"


def format_percent(value):
    """Return a signed percentage, because direction is the point of a return."""
    return MISSING if value is None else f"{value:+.2%}"


def format_unsigned_percent(value):
    return MISSING if value is None else f"{value:.2%}"


def format_rsi(value):
    return MISSING if value is None else f"{value:.1f}"


def format_signed_price(value):
    """Return a gain or loss with its sign before the currency."""
    if value is None:
        return MISSING
    sign = "-" if value < 0 else "+"
    return f"{sign}₹{abs(value):,.2f}"


def format_quantity(value):
    return MISSING if value is None else f"{value:,g}"


FORMATTERS = {
    "price": format_price,
    "percent": format_percent,
    "unsigned_percent": format_unsigned_percent,
    "rsi": format_rsi,
}


def bars_to_frame(bars):
    """Turn the API's list of bars into a table indexed by date."""
    frame = pd.DataFrame(bars)
    frame["date"] = pd.to_datetime(frame["date"])
    return frame.set_index("date").sort_index()


def add_indicators(frame, latest_bar_in_progress):
    """Add moving averages and RSI, using finished sessions only.

    An unfinished bar's price is still changing, so including it here would make
    the charts disagree with /metrics, which also leaves it out.
    """
    closes = frame["close"].iloc[:-1] if latest_bar_in_progress else frame["close"]
    result = frame.copy()
    for window in analytics.SMA_WINDOWS:
        result[f"sma_{window}"] = analytics.sma(closes, window)
    result["rsi_14"] = analytics.rsi(closes)
    return result


def crop_to_view(frame, view):
    """Keep the bars of one view. Indicators stay as calculated on the full history."""
    return frame[frame.index > frame.index[-1] - VIEWS[view]]


def comparison_table(metrics_by_ticker):
    """Return formatted metrics with one column per stock."""
    table = {
        ticker: {
            label: FORMATTERS[kind](metrics[field])
            for field, (label, kind) in COMPARISON_ROWS.items()
        }
        for ticker, metrics in metrics_by_ticker.items()
    }
    return pd.DataFrame(table)


def full_table_height(table):
    """Return the height that shows every row and the header with no inner scroll."""
    return (len(table) + 1) * TABLE_ROW_HEIGHT + 3


def table_view(frame):
    """Return every plotted value as text, newest first, for reading without hover."""
    table = pd.DataFrame(index=frame.index.strftime("%Y-%m-%d"))
    table.index.name = "Date"
    for column, label in [("open", "Open"), ("high", "High"), ("low", "Low"), ("close", "Close")]:
        table[label] = frame[column].map(format_price).to_numpy()
    table["Adj Close"] = [format_price(None if pd.isna(v) else v) for v in frame["adj_close"]]
    table["Volume"] = frame["volume"].map("{:,}".format).to_numpy()
    for column, label in PRICE_SERIES.items():
        if column != "close":
            table[label] = [format_price(None if pd.isna(v) else v) for v in frame[column]]
    table["RSI 14"] = [format_rsi(None if pd.isna(v) else v) for v in frame["rsi_14"]]
    return table.iloc[::-1]


def holdings_table(holdings):
    """Return one formatted row per holding. Unknown values stay n/a."""
    rows = [
        {
            "Stock": holding["ticker"],
            "Quantity": format_quantity(holding["quantity"]),
            "Average cost": format_price(holding["average_cost"]),
            "Invested": format_price(holding["invested"]),
            "Last close": format_price(holding["last_close"]),
            "Close date": holding["last_close_date"] or MISSING,
            "Market value": format_price(holding["market_value"]),
            "Unrealised": format_signed_price(holding["unrealised"]),
            "Unrealised %": format_percent(holding["unrealised_fraction"]),
            "Realised": format_signed_price(holding["realised"]),
        }
        for holding in holdings
    ]
    return pd.DataFrame(rows).set_index("Stock")


def watchlist_table(stocks):
    """Return one row per followed stock, with readable headings."""
    rows = [
        {
            "Stock": stock["ticker"],
            "NSE symbol": stock["nse_symbol"],
            "F&O": "Yes" if stock["is_fno"] else "No",
            "Market close": stock["market_close"],
        }
        for stock in stocks
    ]
    return pd.DataFrame(rows).set_index("Stock")


def analytics_table(stocks):
    """Return one row per stock, keeping the API's order of biggest rise first."""
    above = {True: "Above", False: "Below", None: MISSING}
    rows = [
        {
            "Stock": stock["ticker"],
            "Last bar": stock["last_bar"],
            "Close": format_price(stock["close"]),
            "1D change": format_percent(stock["change_1d"]),
            "From 52W high": format_percent(stock["distance_from_52w_high"]),
            "SMA 200": above[stock["above_sma_200"]],
            "RSI 14": format_rsi(stock["rsi_14"]),
        }
        for stock in stocks
    ]
    return pd.DataFrame(rows).set_index("Stock")


def example_ai_note(stocks):
    """Fill in a note for the demo, which never contacts Gemini, from the report's values."""
    parts = [
        f"{stock['ticker']} changed {format_percent(stock['change_1d'])} "
        f"with an RSI of {format_rsi(stock['rsi_14'])}"
        for stock in stocks[:2]
        if not stock["problem"]
    ]
    return f"EXAMPLE: {', and '.join(parts)}." if parts else "EXAMPLE: no stocks to describe."


def alert_label(alert):
    return f"{alert['ticker']}: {ALERT_KINDS[alert['kind']]} {alert['threshold']:,.2f}"


def alerts_table(alerts):
    rows = [
        {
            "Alert": alert_label(alert),
            "Condition now": "Met" if alert["was_met"] else "Not met",
            "Last session checked": alert["last_checked_bar"] or "Not checked yet",
        }
        for alert in alerts
    ]
    return pd.DataFrame(rows).set_index("Alert")


def trades_table(trades):
    """Return one formatted row per trade, newest first."""
    rows = [
        {
            "Date": trade["trade_date"],
            "Stock": trade["ticker"],
            "Side": trade["side"].capitalize(),
            "Quantity": format_quantity(trade["quantity"]),
            "Price": format_price(trade["price"]),
        }
        for trade in reversed(trades)
    ]
    return pd.DataFrame(rows).set_index("Date")


def trade_label(trade):
    """Describe a trade in the list of trades that can be deleted."""
    return (
        f"{trade['trade_date']} {trade['side']} {format_quantity(trade['quantity'])} "
        f"{trade['ticker']} at {format_price(trade['price'])}"
    )


def apply_style(figure, theme, height):
    """Give a chart the shared quiet look and a crosshair with one tooltip."""
    colors = THEMES[theme]
    figure.update_layout(
        height=height,
        margin={"l": 8, "r": RIGHT_MARGIN_FOR_LABELS, "t": 8, "b": 8},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font={"family": 'system-ui, -apple-system, "Segoe UI", sans-serif', "color": colors["text"]},
        hovermode="x unified",
        legend={"orientation": "h", "x": 0, "y": 1.08, "yanchor": "bottom"},
    )
    # automargin grows the plot's margins to fit the tick labels, instead of clipping them.
    figure.update_xaxes(
        automargin=True,
        showgrid=False,
        linecolor=colors["axis"],
        tickfont={"color": colors["muted"]},
        showspikes=True,
        spikemode="across",
        spikethickness=1,
        spikedash="solid",
        spikecolor=colors["axis"],
    )
    figure.update_yaxes(
        automargin=True,
        gridcolor=colors["grid"],
        gridwidth=1,
        griddash="solid",
        zeroline=False,
        tickfont={"color": colors["muted"]},
    )
    return figure


def end_labels(frame, theme):
    """Return plot annotations naming each line at its right end.

    When lines end close together a label is left out rather than nudged away
    from its line. The legend, tooltip and table view still identify that line.
    """
    last_values = {
        label: frame[column].dropna()
        for column, label in PRICE_SERIES.items()
        if frame[column].notna().any()
    }
    low = min(series.min() for series in last_values.values())
    high = max(series.max() for series in last_values.values())
    minimum_gap = (high - low) * MIN_LABEL_GAP

    annotations = []
    placed = []
    for label, series in last_values.items():
        value = series.iloc[-1]
        if any(abs(value - other) < minimum_gap for other in placed):
            continue
        placed.append(value)
        annotations.append(
            {
                "x": series.index[-1],
                "y": value,
                "text": label,
                "xanchor": "left",
                "xshift": 6,
                "showarrow": False,
                "font": {"color": THEMES[theme]["text"]},
            }
        )
    return annotations


def price_chart(frame, theme):
    """Return Close and its moving averages. Each line has a fixed color for its name."""
    figure = go.Figure()
    for (column, label), color in zip(PRICE_SERIES.items(), THEMES[theme]["series"]):
        if frame[column].notna().any():
            figure.add_scatter(
                x=frame.index,
                y=frame[column],
                name=label,
                mode="lines",
                line={"color": color, "width": LINE_WIDTH},
                connectgaps=False,
                hovertemplate="₹%{y:,.2f}",
            )
    figure.update_layout(annotations=end_labels(frame, theme))
    apply_style(figure, theme, height=420)
    figure.update_yaxes(tickformat=",.0f", tickprefix="₹")
    return figure


def volume_chart(frame, theme):
    """Return traded volume per session. This is one series, so it has no legend."""
    figure = go.Figure()
    figure.add_bar(
        x=frame.index,
        y=frame["volume"],
        name="Volume",
        marker={"color": THEMES[theme]["series"][0], "line": {"width": 0}},
        hovertemplate="%{y:,.0f} shares",
    )
    figure.update_layout(showlegend=False, bargap=0.3)
    apply_style(figure, theme, height=200)
    figure.update_yaxes(tickformat="~s")
    return figure


def rsi_chart(frame, theme):
    """Return RSI on a fixed 0 to 100 scale with its two conventional levels."""
    colors = THEMES[theme]
    figure = go.Figure()
    figure.add_scatter(
        x=frame.index,
        y=frame["rsi_14"],
        name="RSI 14",
        mode="lines",
        line={"color": colors["series"][0], "width": LINE_WIDTH},
        connectgaps=False,
        hovertemplate="%{y:.1f}",
    )
    for level in RSI_REFERENCE_LEVELS:
        figure.add_hline(
            y=level,
            line={"color": colors["axis"], "width": 1, "dash": "solid"},
            annotation_text=str(level),
            annotation_position="right",
            annotation_font={"color": colors["muted"]},
        )
    figure.update_layout(showlegend=False)
    figure.update_yaxes(range=[0, 100], tickvals=[0, 50, 100])
    return apply_style(figure, theme, height=200)

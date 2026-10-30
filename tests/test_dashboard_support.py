"""Tests for dashboard_support.py. These never touch the network.

All prices below are SYNTHETIC TEST DATA, not real market values.
"""

import httpx
import pandas as pd
import pytest

import analytics
import dashboard_support as support


def make_bars(closes, start="2026-01-01", adj_close=True):
    dates = pd.date_range(start, periods=len(closes), freq="D")
    return [
        {
            "date": f"{day:%Y-%m-%d}",
            "open": close,
            "high": close + 1,
            "low": close - 1,
            "close": close,
            "adj_close": close if adj_close else None,
            "volume": 1000,
        }
        for day, close in zip(dates, closes)
    ]


def make_frame(count=30, in_progress=False):
    bars = make_bars([100.0 + i for i in range(count)])
    return support.add_indicators(support.bars_to_frame(bars), in_progress)


def api_answer(monkeypatch, status, body):
    def fake_get(url, timeout):
        return httpx.Response(status, json=body, request=httpx.Request("GET", url))

    monkeypatch.setattr(support.httpx, "get", fake_get)


def annotation_names(figure):
    return [annotation.text for annotation in figure.layout.annotations]


def test_fetch_returns_the_json_answer(monkeypatch):
    api_answer(monkeypatch, 200, {"status": "ok"})
    assert support.fetch_json("/health") == {"status": "ok"}


def test_fetch_reports_a_stopped_api(monkeypatch):
    def refuse(url, timeout):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(support.httpx, "get", refuse)

    with pytest.raises(support.ApiNotRunning):
        support.fetch_json("/health")


def test_fetch_reports_a_timeout_as_not_reachable(monkeypatch):
    def time_out(url, timeout):
        raise httpx.ReadTimeout("too slow")

    monkeypatch.setattr(support.httpx, "get", time_out)

    with pytest.raises(support.ApiNotRunning):
        support.fetch_json("/health")


def test_fetch_passes_on_the_reasons_for_missing_data(monkeypatch):
    api_answer(monkeypatch, 503, {"detail": {"message": "x", "failures": ["Yahoo: down"]}})

    with pytest.raises(support.DataUnavailable) as error:
        support.fetch_json("/stocks/TCS.NS/metrics")

    assert error.value.failures == ["Yahoo: down"]


def test_fetch_does_not_hide_other_errors(monkeypatch):
    api_answer(monkeypatch, 404, {"detail": "Unknown ticker"})

    with pytest.raises(httpx.HTTPStatusError):
        support.fetch_json("/stocks/NOPE.NS/metrics")


@pytest.mark.parametrize(
    ("formatter", "value", "expected"),
    [
        (support.format_price, 1234567.5, "₹1,234,567.50"),
        (support.format_percent, 0.0139, "+1.39%"),
        (support.format_percent, -0.3059, "-30.59%"),
        (support.format_unsigned_percent, 0.2235, "22.35%"),
        (support.format_rsi, 44.1, "44.1"),
    ],
)
def test_formatting(formatter, value, expected):
    assert formatter(value) == expected


@pytest.mark.parametrize(
    "formatter",
    [
        support.format_price,
        support.format_percent,
        support.format_unsigned_percent,
        support.format_rsi,
    ],
)
def test_missing_value_is_never_shown_as_a_number(formatter):
    assert formatter(None) == "n/a"


def test_bars_become_a_table_indexed_by_date():
    frame = support.bars_to_frame(make_bars([100.0, 101.0]))
    assert frame.index[0] == pd.Timestamp("2026-01-01")
    assert frame["close"].tolist() == [100.0, 101.0]


def test_indicators_match_analytics():
    frame = make_frame(30)
    assert frame["sma_20"].iloc[-1] == pytest.approx(119.5)  # mean of 110 to 129
    assert frame["sma_50"].isna().all()
    assert frame["rsi_14"].iloc[-1] == 100


def test_unfinished_bar_stays_visible_but_is_left_out_of_indicators():
    frame = make_frame(30, in_progress=True)
    assert frame["close"].iloc[-1] == 129.0
    assert pd.isna(frame["sma_20"].iloc[-1])
    assert pd.isna(frame["rsi_14"].iloc[-1])
    assert frame["sma_20"].iloc[-2] == pytest.approx(118.5)  # mean of 109 to 128


def test_view_keeps_indicators_calculated_on_the_full_history():
    frame = support.add_indicators(
        support.bars_to_frame(make_bars([100.0 + i for i in range(100)])), False
    )
    cropped = support.crop_to_view(frame, "1 month")
    assert len(cropped) < 35
    assert cropped["sma_50"].notna().all()


@pytest.mark.parametrize(
    ("view", "first_day"),
    [("1 month", "2026-04-11"), ("6 months", "2025-11-11"), ("1 year", "2025-05-11")],
)
def test_views_start_just_after_the_same_date_earlier(view, first_day):
    frame = make_frame(500)
    frame.index = pd.date_range(end="2026-05-10", periods=500, freq="D")
    assert support.crop_to_view(frame, view).index[0] == pd.Timestamp(first_day)


def test_comparison_table_formats_each_metric_and_keeps_nulls():
    metrics = {field: 0.5 for field in support.COMPARISON_ROWS} | {"sma_200": None}
    table = support.comparison_table({"TCS.NS": metrics})
    assert table.loc["Close", "TCS.NS"] == "₹0.50"
    assert table.loc["Total return", "TCS.NS"] == "+50.00%"
    assert table.loc["Volatility (ann.)", "TCS.NS"] == "50.00%"
    assert table.loc["RSI 14", "TCS.NS"] == "0.5"
    assert table.loc["SMA 200", "TCS.NS"] == "n/a"


def test_table_view_is_newest_first_and_shows_unknown_values_as_na():
    table = support.table_view(make_frame(3))
    assert table.index[0] == "2026-01-03"
    assert table.iloc[0]["Close"] == "₹102.00"
    assert table.iloc[0]["Volume"] == "1,000"
    assert table.iloc[0]["SMA 20"] == "n/a"
    assert table.iloc[0]["RSI 14"] == "n/a"


def test_table_view_shows_a_source_without_adj_close_as_na():
    bars = make_bars([100.0, 101.0], adj_close=False)
    table = support.table_view(support.add_indicators(support.bars_to_frame(bars), False))
    assert table.iloc[0]["Adj Close"] == "n/a"


def test_price_chart_leaves_out_lines_with_no_data():
    names = [trace.name for trace in support.price_chart(make_frame(30), "light").data]
    assert names == ["Close", "SMA 20"]


def test_each_price_line_keeps_its_color_when_others_are_missing():
    short = support.price_chart(make_frame(30), "light")
    full = support.price_chart(make_frame(250), "light")
    assert short.data[1].line.color == full.data[1].line.color
    assert [trace.name for trace in full.data] == ["Close", "SMA 20", "SMA 50", "SMA 200"]


def test_price_chart_does_not_join_lines_across_a_gap():
    assert all(not trace.connectgaps for trace in support.price_chart(make_frame(30), "light").data)


def test_dark_theme_uses_its_own_colors():
    light = support.price_chart(make_frame(30), "light").data[0].line.color
    dark = support.price_chart(make_frame(30), "dark").data[0].line.color
    assert light != dark


def test_lines_that_end_apart_are_labelled_directly():
    frame = make_frame(30)
    frame["close"] = 100.0
    frame.loc[frame.index[-1], "close"] = 200.0
    assert annotation_names(support.price_chart(frame, "light")) == ["Close", "SMA 20"]


def test_lines_that_end_together_do_not_get_overlapping_labels():
    frame = make_frame(30)
    frame["sma_20"] = frame["close"]
    assert annotation_names(support.price_chart(frame, "light")) == ["Close"]


def test_charts_have_a_single_price_scale():
    # Close, moving averages and volume never share a plot on two y-axes.
    figure = support.price_chart(make_frame(250), "light")
    assert {trace.yaxis for trace in figure.data} <= {None, "y"}
    assert "volume" not in [trace.name.lower() for trace in figure.data]


def test_volume_chart_is_one_series_without_a_legend():
    figure = support.volume_chart(make_frame(5), "light")
    assert len(figure.data) == 1
    assert figure.layout.showlegend is False


def test_rsi_chart_uses_a_fixed_scale_and_its_reference_levels():
    figure = support.rsi_chart(make_frame(30), "light")
    assert list(figure.layout.yaxis.range) == [0, 100]
    assert sorted(shape.y0 for shape in figure.layout.shapes) == [30, 70]


@pytest.mark.parametrize("chart", [support.price_chart, support.volume_chart, support.rsi_chart])
def test_axes_make_room_for_their_labels(chart):
    # Without this, the page clipped 1,600 down to its last character.
    figure = chart(make_frame(30), "light")
    assert figure.layout.xaxis.automargin is True
    assert figure.layout.yaxis.automargin is True


def test_comparison_table_is_tall_enough_for_every_row():
    metrics = {field: 0.5 for field in support.COMPARISON_ROWS}
    table = support.comparison_table({"TCS.NS": metrics})
    assert support.full_table_height(table) >= (len(support.COMPARISON_ROWS) + 1) * 35


def test_gridlines_are_never_dashed():
    figure = support.price_chart(make_frame(30), "light")
    assert figure.layout.yaxis.griddash == "solid"


def test_rsi_window_matches_the_analytics_default():
    assert analytics.RSI_WINDOW == 14

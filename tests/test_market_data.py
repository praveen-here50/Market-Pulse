"""Tests for the market_data package and check_providers.py. No network is used.

All bhavcopy files below are SYNTHETIC TEST DATA written in NSE's layout. Their
prices are not real market values.
"""

import pandas as pd
import pytest

import check_providers
from market_data import service, yahoo
from market_data.bhavcopy import BhavcopyFileProvider, ProviderError
from market_data.compare import compare_closes
from market_data.instruments import (
    FNO_MARKET_CLOSE,
    INSTRUMENTS,
    NON_FNO_MARKET_CLOSE,
    Instrument,
    market_close_for,
)

HEADER = (
    "SYMBOL, SERIES, DATE1, PREV_CLOSE, OPEN_PRICE, HIGH_PRICE, LOW_PRICE, LAST_PRICE, "
    "CLOSE_PRICE, AVG_PRICE, TTL_TRD_QNTY, TURNOVER_LACS, NO_OF_TRADES, DELIV_QTY, DELIV_PER"
)


def bhavcopy_row(symbol, series, date, prev_close, close):
    return (
        f"{symbol}, {series}, {date}, {prev_close}, {close}, {close + 2}, {close - 2}, "
        f"{close}, {close}, {close}, 1000, 10.0, 50, -, -"
    )


def write_file(folder, name, *rows):
    (folder / name).write_text("\n".join([HEADER, *rows]), encoding="utf-8")


def three_sessions(folder):
    write_file(folder, "a.csv", bhavcopy_row("TCS", "EQ", "27-Oct-2026", 100.0, 101.0))
    write_file(folder, "b.csv", bhavcopy_row("TCS", "EQ", "28-Oct-2026", 101.0, 103.0))
    write_file(folder, "c.csv", bhavcopy_row("TCS", "EQ", "29-Oct-2026", 103.0, 102.0))


def closes(dates, values):
    index = pd.DatetimeIndex(dates, tz="Asia/Kolkata")
    return pd.DataFrame({"Close": values}, index=index)


class FakeProvider:
    def __init__(self, name, table=None, error=None):
        self.name = name
        self.table = table
        self.error = error

    def fetch_daily(self, ticker, period):
        if self.error:
            raise self.error
        return self.table


def no_problems(table):
    return []


def test_fno_stock_closes_after_the_auction():
    assert Instrument("X", is_fno=True).market_close == FNO_MARKET_CLOSE


def test_non_fno_stock_closes_at_1530():
    assert Instrument("X", is_fno=False).market_close == NON_FNO_MARKET_CLOSE


def test_followed_stocks_use_their_own_closing_time():
    assert all(market_close_for(ticker) == FNO_MARKET_CLOSE for ticker in INSTRUMENTS)


def test_unknown_stock_has_no_guessed_closing_time():
    with pytest.raises(KeyError):
        market_close_for("UNKNOWN.NS")


def test_bhavcopy_gives_the_standard_table(tmp_path):
    three_sessions(tmp_path)

    bars = BhavcopyFileProvider(tmp_path).fetch_daily("TCS.NS", "1mo")

    assert list(bars.columns) == ["Open", "High", "Low", "Close", "Volume"]
    assert bars["Close"].tolist() == [101.0, 103.0, 102.0]
    assert bars["High"].iloc[0] == 103.0
    assert bars["Low"].iloc[0] == 99.0
    assert bars["Volume"].iloc[0] == 1000
    assert bars.index[0] == pd.Timestamp("2026-10-27", tz="Asia/Kolkata")


def test_bhavcopy_date_comes_from_inside_the_file(tmp_path):
    # NSE's file named after a non-trading day repeats the previous session.
    row = bhavcopy_row("TCS", "EQ", "23-Oct-2026", 100.0, 101.0)
    write_file(tmp_path, "sec_bhavdata_full_25102026.csv", row)

    bars = BhavcopyFileProvider(tmp_path).fetch_daily("TCS.NS", "1mo")

    assert bars.index[0] == pd.Timestamp("2026-10-23", tz="Asia/Kolkata")


def test_bhavcopy_repeated_session_is_counted_once(tmp_path):
    row = bhavcopy_row("TCS", "EQ", "23-Oct-2026", 100.0, 101.0)
    write_file(tmp_path, "sec_bhavdata_full_23102026.csv", row)
    write_file(tmp_path, "sec_bhavdata_full_25102026.csv", row)

    assert len(BhavcopyFileProvider(tmp_path).fetch_daily("TCS.NS", "1mo")) == 1


def test_bhavcopy_files_are_ordered_by_session_not_by_name(tmp_path):
    write_file(tmp_path, "a.csv", bhavcopy_row("TCS", "EQ", "28-Oct-2026", 101.0, 103.0))
    write_file(tmp_path, "b.csv", bhavcopy_row("TCS", "EQ", "27-Oct-2026", 100.0, 101.0))

    bars = BhavcopyFileProvider(tmp_path).fetch_daily("TCS.NS", "1mo")

    assert bars["Close"].tolist() == [101.0, 103.0]


def test_bhavcopy_ignores_other_stocks_and_other_series(tmp_path):
    write_file(
        tmp_path,
        "a.csv",
        bhavcopy_row("INFY", "EQ", "23-Oct-2026", 500.0, 501.0),
        bhavcopy_row("TCS", "BE", "23-Oct-2026", 700.0, 701.0),
        bhavcopy_row("TCS", "EQ", "23-Oct-2026", 100.0, 101.0),
    )

    bars = BhavcopyFileProvider(tmp_path).fetch_daily("TCS.NS", "1mo")

    assert bars["Close"].tolist() == [101.0]


def test_bhavcopy_refuses_to_join_across_a_split(tmp_path):
    write_file(tmp_path, "a.csv", bhavcopy_row("TCS", "EQ", "27-Oct-2026", 200.0, 200.0))
    # After a 2-for-1 split NSE restates PREV_CLOSE as 100. Joined, this is a fake crash.
    write_file(tmp_path, "b.csv", bhavcopy_row("TCS", "EQ", "28-Oct-2026", 100.0, 101.0))

    with pytest.raises(ProviderError, match="2026-10-28"):
        BhavcopyFileProvider(tmp_path).fetch_daily("TCS.NS", "1mo")


def test_bhavcopy_refuses_to_join_across_a_missing_file(tmp_path):
    three_sessions(tmp_path)
    (tmp_path / "b.csv").unlink()

    with pytest.raises(ProviderError, match="a file is missing"):
        BhavcopyFileProvider(tmp_path).fetch_daily("TCS.NS", "1mo")


def test_bhavcopy_period_leaves_out_older_files(tmp_path):
    three_sessions(tmp_path)
    # Far older than one month and does not join, so it must simply be left out.
    write_file(tmp_path, "old.csv", bhavcopy_row("TCS", "EQ", "02-Jan-2026", 900.0, 900.0))

    assert len(BhavcopyFileProvider(tmp_path).fetch_daily("TCS.NS", "1mo")) == 3


def test_empty_bhavcopy_folder_gives_an_empty_table(tmp_path):
    assert BhavcopyFileProvider(tmp_path).fetch_daily("TCS.NS", "1mo").empty


def test_bhavcopy_table_has_no_adj_close(tmp_path):
    three_sessions(tmp_path)
    bars = BhavcopyFileProvider(tmp_path).fetch_daily("TCS.NS", "1mo")
    assert "Adj Close" not in bars.columns


def test_first_working_provider_is_used(monkeypatch):
    table = pd.DataFrame({"Close": [1.0]})
    second = FakeProvider("second", error=AssertionError("should not be called"))
    monkeypatch.setattr(service, "PROVIDERS", [FakeProvider("first", table), second])

    result = service.fetch_with_fallback("TCS.NS", "1mo", no_problems)

    assert result.source == "first"
    assert result.failures == []


def test_failed_provider_falls_back_and_stays_on_record(monkeypatch):
    table = pd.DataFrame({"Close": [1.0]})
    first = FakeProvider("first", error=ConnectionError("down"))
    monkeypatch.setattr(service, "PROVIDERS", [first, FakeProvider("second", table)])

    result = service.fetch_with_fallback("TCS.NS", "1mo", no_problems)

    assert result.source == "second"
    assert result.history is table
    assert result.failures == ["first: download failed: ConnectionError: down"]


def test_data_failing_the_check_falls_back(monkeypatch):
    good = pd.DataFrame({"Close": [2.0]})
    bad = pd.DataFrame({"Close": [-1.0]})
    providers = [FakeProvider("first", bad), FakeProvider("second", good)]
    monkeypatch.setattr(service, "PROVIDERS", providers)

    def check(table):
        return ["negative price"] if (table["Close"] < 0).any() else []

    result = service.fetch_with_fallback("TCS.NS", "1mo", check)

    assert result.source == "second"
    assert result.failures == ["first: negative price"]


def test_all_providers_failing_gives_no_data(monkeypatch):
    providers = [
        FakeProvider("first", error=ConnectionError("down")),
        FakeProvider("second", pd.DataFrame()),
    ]
    monkeypatch.setattr(service, "PROVIDERS", providers)

    result = service.fetch_with_fallback("TCS.NS", "1mo", lambda table: ["no rows"])

    assert result.history is None
    assert result.source is None
    assert len(result.failures) == 2


def test_compare_finds_a_different_close():
    primary = closes(["2026-10-28", "2026-10-29"], [100.0, 101.0])
    reference = closes(["2026-10-28", "2026-10-29"], [100.0, 202.0])

    result = compare_closes(primary, reference)

    assert result.sessions_compared == 2
    assert result.close_differences["Reference"].tolist() == [202.0]


def test_compare_tolerates_float_noise():
    primary = closes(["2026-10-28"], [1204.300049])
    assert compare_closes(primary, closes(["2026-10-28"], [1204.30])).close_differences.empty


def test_compare_finds_a_session_missing_from_the_primary():
    primary = closes(["2026-10-28"], [100.0])
    reference = closes(["2026-10-27", "2026-10-28"], [99.0, 100.0])

    result = compare_closes(primary, reference)

    assert list(result.missing_from_primary) == [pd.Timestamp("2026-10-27", tz="Asia/Kolkata")]


def test_compare_does_not_report_primary_history_outside_the_reference():
    primary = closes(["2026-10-27", "2026-10-28"], [99.0, 100.0])
    result = compare_closes(primary, closes(["2026-10-28"], [100.0]))
    assert result.sessions_compared == 1
    assert len(result.missing_from_primary) == 0


def yahoo_bars(closing_prices, volume=1000):
    dates = pd.date_range("2026-10-27", periods=len(closing_prices), tz="Asia/Kolkata")
    close = pd.Series(closing_prices, index=dates, dtype="float64")
    return pd.DataFrame({"High": close + 2, "Low": close - 2, "Close": close, "Volume": volume})


def test_check_reports_a_session_yahoo_only_filled_with_a_placeholder(tmp_path):
    three_sessions(tmp_path)
    yahoo = yahoo_bars([101.0, 101.0, 102.0])
    yahoo.iloc[1, yahoo.columns.get_indexer(["High", "Low"])] = 101.0
    yahoo.iloc[1, yahoo.columns.get_loc("Volume")] = 0

    lines, agreed = check_providers.check_symbol(
        "TCS.NS", FakeProvider("yahoo", yahoo), BhavcopyFileProvider(tmp_path)
    )

    assert not agreed
    assert "2026-10-28 traded on NSE but has no real bar on Yahoo" in lines[1]


def test_check_passes_when_sources_agree(tmp_path):
    three_sessions(tmp_path)
    lines, agreed = check_providers.check_symbol(
        "TCS.NS", FakeProvider("yahoo", yahoo_bars([101.0, 103.0, 102.0])), BhavcopyFileProvider(tmp_path)
    )
    assert agreed
    assert lines == ["TCS.NS: 3 session(s) compared"]


def test_check_without_files_does_not_claim_agreement(tmp_path):
    lines, agreed = check_providers.check_symbol(
        "TCS.NS", FakeProvider("yahoo", yahoo_bars([100.0])), BhavcopyFileProvider(tmp_path)
    )
    assert not agreed
    assert "no bars found" in lines[0]


class FakeTicker:
    def __init__(self, history):
        self.table = history

    def history(self, **options):
        return self.table


def test_yahoo_splits_come_back_as_dates_and_ratios(monkeypatch):
    dates = pd.date_range("2025-08-25", periods=3, freq="D", tz="Asia/Kolkata")
    table = pd.DataFrame({"Stock Splits": [0.0, 2.0, 0.0]}, index=dates)
    monkeypatch.setattr(yahoo.yf, "Ticker", lambda ticker: FakeTicker(table))

    assert yahoo.YahooProvider().fetch_splits("TCS.NS", "2025-08-01") == {"2025-08-26": 2.0}


def test_yahoo_rows_without_splits_mean_no_splits(monkeypatch):
    dates = pd.date_range("2025-08-25", periods=2, freq="D", tz="Asia/Kolkata")
    table = pd.DataFrame({"Stock Splits": [0.0, 0.0]}, index=dates)
    monkeypatch.setattr(yahoo.yf, "Ticker", lambda ticker: FakeTicker(table))

    assert yahoo.YahooProvider().fetch_splits("TCS.NS", "2025-08-01") == {}


def test_yahoo_empty_history_is_a_failure_and_not_no_splits(monkeypatch):
    monkeypatch.setattr(yahoo.yf, "Ticker", lambda ticker: FakeTicker(pd.DataFrame()))

    with pytest.raises(ConnectionError):
        yahoo.YahooProvider().fetch_splits("TCS.NS", "2025-08-01")


def test_splits_are_never_assumed_when_no_provider_has_them(monkeypatch):
    monkeypatch.setattr(service, "PROVIDERS", [FakeProvider("no split history")])

    with pytest.raises(service.SplitsUnavailable):
        service.fetch_splits("TCS.NS", "2025-08-01")

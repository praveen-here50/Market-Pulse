"""Tests for commentary.py and GET /summary?ai=true. These never contact Gemini.

All prices and AI replies below are SYNTHETIC TEST DATA. The database goes to a
temporary folder, set up in conftest.py.
"""

import json

import httpx
import pandas as pd
import pytest
from fastapi.testclient import TestClient

import api
import commentary
import fetch_prices
from market_data import service

NOW = pd.Timestamp("2026-10-30 19:00", tz="Asia/Kolkata")
KEY = "fake-test-key"
DATA = (
    "TCS.NS: 2,502.60 INR on 2026-10-30, 1D -0.99%, RSI 67.2\n"
    "INFY.NS: 1,185.00 INR on 2026-10-30, 1D +3.36%, RSI 64.4"
)
GOOD_NOTE = "INFY.NS changed +3.36% to 1,185.00 INR, and TCS.NS changed -0.99%. RSI was 67.2 for TCS.NS."

client = TestClient(api.app)


def reply(text=GOOD_NOTE, finish="STOP", parts=None):
    return {
        "candidates": [
            {"content": {"parts": parts or [{"text": text}]}, "finishReason": finish}
        ]
    }


class FakeGemini:
    """Stands in for httpx.post and records what would have left this computer."""

    def __init__(self, body=None, status=200, error=None):
        self.body = reply() if body is None else body
        self.status = status
        self.error = error
        self.requests = []

    def __call__(self, url, headers, json, timeout):
        self.requests.append({"url": url, "headers": headers, "json": json})
        if self.error:
            raise self.error
        return httpx.Response(self.status, json=self.body)


@pytest.fixture
def gemini(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", KEY)
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    monkeypatch.delenv("MARKETPULSE_GEMINI_URL", raising=False)

    def install(fake=None):
        fake = fake or FakeGemini()
        monkeypatch.setattr(commentary.httpx, "post", fake)
        return fake

    return install


def make_history(bars=30):
    close = pd.Series([100.0 + i for i in range(bars)])
    history = pd.DataFrame(
        {
            "Open": close,
            "High": close + 1,
            "Low": close - 1,
            "Close": close,
            "Adj Close": close,
            "Volume": 1000,
        }
    )
    return history.set_index(
        pd.date_range(end="2026-10-30", periods=bars, freq="D", tz="Asia/Kolkata")
    )


class FakeProvider:
    name = "Fake provider"

    def __init__(self, broken=()):
        self.broken = broken

    def fetch_daily(self, ticker, period):
        if ticker in self.broken:
            raise ConnectionError("simulated outage")
        return make_history()

    def fetch_splits(self, ticker, since):
        return {}


@pytest.fixture
def market(monkeypatch):
    def install(provider=None):
        monkeypatch.setattr(service, "PROVIDERS", [provider or FakeProvider()])
        monkeypatch.setattr(fetch_prices.pd.Timestamp, "now", lambda tz=None: NOW)

    install()
    return install


def test_a_good_note_passes():
    assert commentary.find_problem(GOOD_NOTE, DATA) is None


@pytest.mark.parametrize(
    "note",
    [
        "TCS.NS closed at 2,510.00 INR.",
        "TCS.NS has an RSI of 70.",
        "INFY.NS changed +3.4%.",
        "TCS.NS changed +5%.",
        "On 2026-10-29 TCS.NS closed at 2,502.60 INR.",
        "Over 200 sessions TCS.NS changed.",
    ],
)
def test_invented_figures_are_rejected(note):
    assert "number" in commentary.find_problem(note, DATA)


def test_a_number_cannot_borrow_from_a_date():
    # 30 is inside the date 2026-10-30, but that is not an RSI of 30.
    assert commentary.find_problem("RSI reached 30.", DATA) is not None
    # Read without the date rule, its digits would give -10 and -30.
    assert commentary.find_problem("TCS.NS changed -30%.", DATA) is not None


def test_the_same_number_in_another_format_passes():
    assert commentary.find_problem("TCS.NS closed at 2502.6 INR.", DATA) is None
    assert commentary.find_problem("TCS.NS changed -0.990%.", DATA) is None


@pytest.mark.parametrize(
    "note",
    [
        "You should buy INFY.NS.",
        "SELL TCS.NS now.",
        "Consider holding TCS.NS.",
        "We recommend INFY.NS.",
        "TCS.NS will rise tomorrow.",
        "INFY.NS could fall.",
        "The target for TCS.NS is higher.",
        "TCS.NS is likely to recover.",
        "Analysts expect gains.",
        "INFY.NS rose due to strong earnings.",
        "TCS.NS fell because of weak demand.",
        "TCS.NS fell 0.99%.",
        "INFY.NS rose 3.36%.",
        "TCS.NS closed lower.",
        "INFY.NS gained, driven by exports.",
    ],
)
def test_advice_predictions_and_invented_causes_are_rejected(note):
    assert "advice" in commentary.find_problem(note, DATA)


def test_a_change_with_the_wrong_sign_is_rejected():
    # The data says -0.99% and +3.36%, so these two reverse what really happened.
    assert "number" in commentary.find_problem("TCS.NS changed +0.99%.", DATA)
    assert "number" in commentary.find_problem("INFY.NS changed -3.36%.", DATA)


def test_a_fall_cannot_lose_its_sign():
    assert "number" in commentary.find_problem("TCS.NS changed 0.99%.", DATA)


def test_ordinary_words_are_not_rejected_by_accident():
    note = "TCS.NS changed, with shareholders seeing RSI 67.2 and upward buyers absent."
    assert commentary.find_problem(note, DATA) is None


def test_an_overlong_note_is_rejected():
    assert "too long" in commentary.find_problem("word " * 200, DATA)


def test_an_empty_note_is_rejected():
    assert "no text" in commentary.find_problem("", DATA)


def test_no_key_means_no_request(gemini, monkeypatch):
    fake = gemini()
    monkeypatch.delenv("GEMINI_API_KEY")

    note = commentary.write_note([DATA])

    assert note.text is None
    assert note.problem == "GEMINI_API_KEY is not set"
    assert fake.requests == []


def test_no_prices_means_no_request(gemini):
    fake = gemini()

    assert commentary.write_note([]).problem == "no prices to describe"
    assert fake.requests == []


def test_the_key_goes_in_a_header_and_never_in_the_url(gemini):
    fake = gemini()

    commentary.write_note([DATA])

    assert fake.requests[0]["headers"] == {"x-goog-api-key": KEY}
    assert KEY not in fake.requests[0]["url"]
    assert KEY not in json.dumps(fake.requests[0]["json"])


def test_the_model_can_be_changed(gemini, monkeypatch):
    fake = gemini()
    monkeypatch.setenv("GEMINI_MODEL", "gemini-test")

    commentary.write_note([DATA])

    assert fake.requests[0]["url"].endswith("/models/gemini-test:generateContent")


def test_a_cut_off_answer_is_not_used(gemini):
    gemini(FakeGemini(reply(finish="MAX_TOKENS")))

    note = commentary.write_note([DATA])

    assert note.text is None
    assert "MAX_TOKENS" in note.problem


def test_a_blocked_prompt_is_reported(gemini):
    gemini(FakeGemini({"promptFeedback": {"blockReason": "SAFETY"}}))

    assert commentary.write_note([DATA]).problem == "Gemini refused the request"


def test_the_models_thoughts_are_left_out(gemini):
    parts = [{"text": "I should buy", "thought": True}, {"text": GOOD_NOTE}]
    gemini(FakeGemini(reply(parts=parts)))

    assert commentary.write_note([DATA]).text == GOOD_NOTE


@pytest.mark.parametrize("status", [400, 401, 403, 429, 500, 503])
def test_an_error_status_gives_a_reason(gemini, status):
    gemini(FakeGemini({"error": {"message": f"details with {KEY}"}}, status=status))

    note = commentary.write_note([DATA])

    assert note.text is None
    assert note.problem == f"Gemini answered with status {status}"


@pytest.mark.parametrize("error", [httpx.ConnectError("down"), httpx.ReadTimeout("slow")])
def test_a_network_failure_gives_a_reason_not_a_crash(gemini, error):
    gemini(FakeGemini(error=error))

    assert "could not be reached" in commentary.write_note([DATA]).problem


@pytest.mark.parametrize("body", [{"candidates": "nonsense"}, {"candidates": [1]}, []])
def test_a_strange_answer_gives_a_reason_not_a_crash(gemini, body):
    gemini(FakeGemini(body))

    assert commentary.write_note([DATA]).text is None


def test_summary_without_ai_never_contacts_gemini(market, gemini):
    fake = gemini()

    body = client.get("/summary").json()

    assert fake.requests == []
    assert body["ai_note"] is None
    assert "AI note" not in body["text"]


def test_summary_with_ai_labels_the_note(market, gemini):
    note = "RELIANCE.NS changed +0.78% to 129.00 INR."
    gemini(FakeGemini(reply(note)))

    body = client.get("/summary?ai=true").json()

    assert body["ai_note"] == note
    assert f"AI note (Gemini, can be wrong, not advice): {note}" in body["text"]


def test_the_calculated_numbers_do_not_change_with_ai(market, gemini):
    gemini(FakeGemini(reply("RELIANCE.NS changed +0.78%.")))

    plain = client.get("/summary").json()
    with_ai = client.get("/summary?ai=true").json()

    # Only `notes` may differ: the second request is answered from a saved copy.
    for stocks in (plain["stocks"], with_ai["stocks"]):
        for stock in stocks:
            del stock["notes"]
    assert plain["stocks"] == with_ai["stocks"]


def test_a_rejected_note_still_delivers_the_report(market, gemini):
    gemini(FakeGemini(reply("TCS.NS closed at 9,999.00 INR.")))

    response = client.get("/summary?ai=true")
    body = response.json()

    assert response.status_code == 200
    assert body["ai_note"] is None
    assert "9,999.00" not in body["text"]
    assert "AI note unavailable: Gemini's note was dropped" in body["text"]
    assert "RELIANCE.NS: 129.00 INR" in body["text"]


def test_a_gemini_outage_still_delivers_the_report(market, gemini):
    gemini(FakeGemini(status=503, body={}))

    response = client.get("/summary?ai=true")

    assert response.status_code == 200
    assert "AI note unavailable: Gemini answered with status 503" in response.json()["text"]


def test_a_note_is_escaped_for_telegram(market, gemini):
    gemini(FakeGemini(reply("RELIANCE.NS & TCS.NS each changed +0.78%.")))

    assert "RELIANCE.NS &amp; TCS.NS" in client.get("/summary?ai=true").json()["text_html"]


def test_a_long_note_still_fits_in_a_telegram_message():
    stocks = [
        api.StockSummary(ticker=f"STOCK{number}.NS", close=100.0, last_bar="2026-10-30")
        for number in range(200)
    ]
    long_note = commentary.Commentary(text="x" * commentary.MAX_NOTE_LENGTH)

    text = api.summary_text(stocks, NOW, api.ai_lines(long_note))

    assert len(text) <= 4096
    assert "x" * commentary.MAX_NOTE_LENGTH in text


def test_failure_reasons_are_not_sent_to_gemini(market, gemini):
    market(FakeProvider(broken=["TCS.NS"]))
    fake = gemini(FakeGemini(reply("RELIANCE.NS changed +0.78%.")))

    client.get("/summary?ai=true")

    sent = json.dumps(fake.requests[0]["json"])
    assert "TCS.NS" not in sent
    assert "simulated outage" not in sent


def test_holdings_and_trades_are_never_sent_to_gemini(market, gemini):
    fake = gemini(FakeGemini(reply("RELIANCE.NS changed +0.78%.")))
    client.post(
        "/trades",
        json={"ticker": "TCS.NS", "side": "buy", "quantity": 1357, "price": 864.25, "trade_date": "2026-01-10"},
    )

    client.get("/summary?ai=true")

    sent = json.dumps(fake.requests[0]["json"])
    assert "1357" not in sent
    assert "864.25" not in sent

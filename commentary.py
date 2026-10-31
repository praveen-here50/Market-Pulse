"""MarketPulse Phase 10: ask Gemini for a short note on the day's report.

Gemini only rewords numbers it is given, and everything it returns is checked here,
because a model can invent a figure while sounding sure of it. A note that fails any
check is dropped whole, and the report goes out without it.

Only watchlist prices are sent. On Gemini's free tier people at Google may read what
is submitted, so holdings and trades must never reach this module.

The key comes from GEMINI_API_KEY and travels in a header. It stays out of the URL
because URLs get printed in logs and error messages.
"""

import os
import re
from dataclasses import dataclass

import httpx

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models"
DEFAULT_MODEL = "gemini-3.5-flash-lite"
TIMEOUT_SECONDS = 30
MAX_NOTE_LENGTH = 600

INSTRUCTIONS = (
    "You describe one day of Indian stock prices for a student's learning project. "
    "Write at most three plain sentences saying which stocks moved most and how their "
    "RSI values compare. Use only the data given, and copy numbers exactly as written, "
    "keeping the + or - sign of each 1D change, such as 'changed -0.99%'. Do not use "
    "direction words like rose, fell, up, down, higher or lower. Do not count things "
    "or add any other number. Do not explain why a price moved, because you have no "
    "news. Do not predict anything. Do not give advice or say what anyone should do."
)

# A date stays whole, so the 30 in 2026-10-30 cannot excuse an invented "RSI of 30".
# A sign stays with its number, so a fall of 0.99% cannot be reported as a rise.
FIGURE = re.compile(r"\d{4}-\d{2}-\d{2}|[+-]?\d+(?:,\d{3})*(?:\.\d+)?")

# Advice, predictions, and causes: Gemini has no news, so any reason would be a guess.
# Direction words go too: "fell 0.99%" would pass the number check even after a rise.
FORBIDDEN = re.compile(
    r"\b(buy|buying|sell|selling|hold|holding|recommend\w*|should|must|target\w*"
    r"|forecast\w*|predict\w*|expect\w*|likely|will|could|might|may|outlook"
    r"|because|due to|driven by|thanks to|as a result|amid"
    r"|rose|rise|rising|gain\w*|climb\w*|jump\w*|surg\w*|rall\w*|up|higher"
    r"|fell|fall\w*|drop\w*|declin\w*|slip\w*|slid|plung\w*|los[st]\w*|down|lower)\b",
    re.IGNORECASE,
)


@dataclass
class Commentary:
    text: str | None = None
    problem: str | None = None


def figures_in(text):
    """Return every date and number in a text, so 2,502.60 and 2502.6 count as equal."""
    return {
        figure if figure.count("-") == 2 else float(figure.replace(",", ""))
        for figure in FIGURE.findall(text)
    }


def find_problem(note, data):
    """Return why a note cannot be used, or None if it passes."""
    if not note:
        return "Gemini returned no text"
    if len(note) > MAX_NOTE_LENGTH:
        return "Gemini's note was too long"
    if FORBIDDEN.search(note):
        return "Gemini's note was dropped: it gave advice, a prediction, a cause or a direction"
    if figures_in(note) - figures_in(data):
        return "Gemini's note was dropped: it had a number that was not in the data"
    return None


def read_note(body):
    """Return (text, problem). A cut-off or blocked answer is not used."""
    candidates = body.get("candidates") or []
    if not candidates:
        return None, "Gemini refused the request"
    if candidates[0].get("finishReason") != "STOP":
        return None, f"Gemini stopped early: {candidates[0].get('finishReason')}"
    parts = candidates[0].get("content", {}).get("parts", [])
    return "".join(part.get("text", "") for part in parts if not part.get("thought")).strip(), None


def write_note(lines):
    """Return a checked Commentary for report lines. This never raises for Gemini's faults."""
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        return Commentary(problem="GEMINI_API_KEY is not set")
    if not lines:
        return Commentary(problem="no prices to describe")

    data = "\n".join(lines)
    base_url = os.environ.get("MARKETPULSE_GEMINI_URL", GEMINI_URL)
    model = os.environ.get("GEMINI_MODEL", DEFAULT_MODEL)
    try:
        response = httpx.post(
            f"{base_url}/{model}:generateContent",
            headers={"x-goog-api-key": key},
            json={
                "systemInstruction": {"parts": [{"text": INSTRUCTIONS}]},
                "contents": [{"role": "user", "parts": [{"text": data}]}],
                "generationConfig": {"temperature": 0.2},
            },
            timeout=TIMEOUT_SECONDS,
        )
    except httpx.HTTPError as error:
        return Commentary(problem=f"Gemini could not be reached: {type(error).__name__}")

    if response.status_code != 200:
        return Commentary(problem=f"Gemini answered with status {response.status_code}")

    try:
        note, problem = read_note(response.json())
    except (ValueError, AttributeError, TypeError):
        return Commentary(problem="Gemini's answer could not be read")

    problem = problem or find_problem(note, data)
    return Commentary(problem=problem) if problem else Commentary(text=note)

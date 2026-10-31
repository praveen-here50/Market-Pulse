"""Check every exported n8n workflow against the project's rules. n8n need not be running.

Exports are committed to git, so anything in them is public. Whether a workflow really
runs is checked by starting n8n, which this file does not do.
"""

import json
from pathlib import Path

import pytest

import api

WORKFLOW_FOLDER = Path(__file__).parent.parent / "automation" / "workflows"
WORKFLOWS = sorted(WORKFLOW_FOLDER.glob("*.json"))

# Words that appear in a field holding a secret.
SECRET_WORDS = ["credentials", "password", "token", "apikey", "api_key", "secret"]

# A workflow may name the credential it uses. The token itself stays in n8n.
TELEGRAM_CREDENTIAL = {
    "telegramApi": {"id": "marketpulseTelegram", "name": "MarketPulse Telegram"}
}


def strings_in(value):
    """Yield every key and text value inside parsed JSON."""
    if isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from strings_in(item)
    elif isinstance(value, list):
        for item in value:
            yield from strings_in(item)
    elif isinstance(value, str):
        yield value


def http_nodes(workflow):
    return [node for node in workflow["nodes"] if node["type"].endswith(".httpRequest")]


def telegram_nodes(workflow):
    return [node for node in workflow["nodes"] if node["type"].endswith(".telegram")]


def load(name):
    return json.loads((WORKFLOW_FOLDER / name).read_text(encoding="utf-8"))


CHAT_ID = "={{ $env.TELEGRAM_CHAT_ID }}"


def test_there_is_a_workflow_to_check():
    assert WORKFLOWS


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda path: path.stem)
class TestEveryWorkflow:
    @pytest.fixture
    def workflow(self, path):
        return json.loads(path.read_text(encoding="utf-8"))

    def test_holds_no_secrets(self, workflow):
        for node in workflow["nodes"]:
            if "credentials" in node:
                assert node.pop("credentials") == TELEGRAM_CREDENTIAL

        found = [
            text
            for text in strings_in(workflow)
            if any(word in text.lower() for word in SECRET_WORDS)
        ]
        assert set(found) <= {CHAT_ID}

    def test_telegram_messages_are_safe_to_send(self, workflow):
        for node in telegram_nodes(workflow):
            parameters = node["parameters"]
            # A private chat ID is never written into a public file.
            assert parameters["chatId"] == CHAT_ID
            # Left unset, n8n sends Markdown, and a stray _ makes Telegram refuse it.
            assert parameters["additionalFields"]["parse_mode"] == "HTML"
            assert parameters["additionalFields"]["appendAttribution"] is False

    def test_is_switched_off_until_the_owner_publishes_it(self, workflow):
        assert workflow["active"] is False

    def test_never_contacts_nse(self, workflow):
        assert not any("nseindia" in text.lower() for text in strings_in(workflow))

    def test_only_calls_the_marketpulse_api(self, workflow):
        for node in http_nodes(workflow):
            assert node["parameters"]["url"].startswith("={{ $env.MARKETPULSE_API_URL }}/")

    def test_calls_paths_the_api_really_has(self, workflow):
        known = {route.path for route in api.app.routes}
        for node in http_nodes(workflow):
            path = node["parameters"]["url"].split("}}", 1)[1].split("?")[0]
            assert path in known

    def test_has_no_saved_sample_data(self, workflow):
        assert workflow.get("pinData", {}) == {}

    def test_every_connection_joins_real_nodes(self, workflow):
        names = {node["name"] for node in workflow["nodes"]}
        for source, outputs in workflow["connections"].items():
            assert source in names
            for branch in outputs["main"]:
                assert {link["node"] for link in branch} <= names


def test_daily_report_runs_after_the_close_on_weekdays_in_ist():
    workflow = load("marketpulse_daily_report.json")
    schedule = next(node for node in workflow["nodes"] if node["type"].endswith(".scheduleTrigger"))

    assert schedule["parameters"]["rule"]["interval"][0]["expression"] == "30 16 * * 1-5"
    # Without this, n8n would use the computer's time zone.
    assert workflow["settings"]["timezone"] == "Asia/Kolkata"


def test_daily_report_sends_the_escaped_text_the_api_returns():
    workflow = load("marketpulse_daily_report.json")
    report = next(node for node in workflow["nodes"] if node["name"] == "Send report")

    assert report["parameters"]["text"] == "={{ $json.text_html }}"
    assert "text_html" in api.SummaryResponse.model_fields


def test_daily_report_asks_for_the_ai_note():
    workflow = load("marketpulse_daily_report.json")
    summary = next(node for node in workflow["nodes"] if node["name"] == "Get summary")

    assert summary["parameters"]["url"].endswith("/summary?ai=true")


def test_only_the_api_contacts_gemini():
    # The key stays with the API, and its checks cannot be skipped by a workflow.
    for path in WORKFLOWS:
        assert "generativelanguage" not in path.read_text(encoding="utf-8")


def test_daily_report_alerts_when_the_api_fails():
    workflow = load("marketpulse_daily_report.json")
    summary = next(node for node in workflow["nodes"] if node["name"] == "Get summary")
    success, failure = workflow["connections"]["Get summary"]["main"]

    assert summary["onError"] == "continueErrorOutput"
    assert success[0]["node"] == "Send report"
    assert failure[0]["node"] == "Send failure alert"


def test_failure_alert_contains_no_price_data():
    workflow = load("marketpulse_daily_report.json")
    alert = next(node for node in workflow["nodes"] if node["name"] == "Send failure alert")

    text = alert["parameters"]["text"]
    assert "$json" not in text
    assert "no prices" in text


def test_summary_workflow_reads_fields_the_api_returns():
    workflow = load("marketpulse_summary.json")
    report = next(node for node in workflow["nodes"] if node["name"] == "Keep the report")

    fields = [item["name"] for item in report["parameters"]["assignments"]["assignments"]]

    assert set(fields) <= set(api.SummaryResponse.model_fields)

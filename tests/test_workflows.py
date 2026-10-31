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

# Words that appear in a field holding a secret. A "credentials" key would point at
# one, and n8n leaves that key out of an export only if no node uses a credential.
SECRET_WORDS = ["credentials", "password", "token", "apikey", "api_key", "secret"]


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


def test_there_is_a_workflow_to_check():
    assert WORKFLOWS


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda path: path.stem)
class TestEveryWorkflow:
    @pytest.fixture
    def workflow(self, path):
        return json.loads(path.read_text(encoding="utf-8"))

    def test_holds_no_secrets(self, workflow):
        found = [
            text
            for text in strings_in(workflow)
            if any(word in text.lower() for word in SECRET_WORDS)
        ]
        assert found == []

    def test_never_contacts_nse(self, workflow):
        assert not any("nseindia" in text.lower() for text in strings_in(workflow))

    def test_only_calls_the_marketpulse_api(self, workflow):
        for node in http_nodes(workflow):
            assert node["parameters"]["url"].startswith("={{ $env.MARKETPULSE_API_URL }}/")

    def test_calls_paths_the_api_really_has(self, workflow):
        known = {route.path for route in api.app.routes}
        for node in http_nodes(workflow):
            assert node["parameters"]["url"].split("}}", 1)[1] in known

    def test_has_no_saved_sample_data(self, workflow):
        assert workflow.get("pinData", {}) == {}

    def test_every_connection_joins_real_nodes(self, workflow):
        names = {node["name"] for node in workflow["nodes"]}
        for source, outputs in workflow["connections"].items():
            assert source in names
            for branch in outputs["main"]:
                assert {link["node"] for link in branch} <= names


def test_summary_workflow_reads_fields_the_api_returns():
    workflow = json.loads((WORKFLOW_FOLDER / "marketpulse_summary.json").read_text(encoding="utf-8"))
    report = next(node for node in workflow["nodes"] if node["name"] == "Keep the report")

    fields = [item["name"] for item in report["parameters"]["assignments"]["assignments"]]

    assert set(fields) <= set(api.SummaryResponse.model_fields)

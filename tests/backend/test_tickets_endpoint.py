import json

from fastapi.testclient import TestClient

from main import app
from services.impact_analysis import AffectedModule

VALID_JSON = json.dumps(
    {
        "epics": [
            {
                "title": "Epic 1",
                "description": "Desc",
                "stories": [
                    {
                        "title": "Story 1",
                        "description": "Desc",
                        "acceptance_criteria": ["AC1"],
                        "test_cases": ["TC1"],
                        "tasks": [{"title": "Task 1", "description": "Desc"}],
                    }
                ],
            }
        ]
    }
)


def _fake_run_feature_plan(repo_id, feature_description, top_k):
    return {
        "plan": "1. Do X.",
        "affected_modules": [
            AffectedModule(file_path="a.py", reason="directly relevant", fan_in=1, has_api_endpoint=False)
        ],
        "risks": ["Some risk."],
    }


class _FakeLLMProvider:
    def complete(self, prompt: str, json_mode: bool = False) -> str:
        return VALID_JSON


def test_tickets_endpoint_returns_plan_and_epics(monkeypatch):
    monkeypatch.setattr("agents.ticket_generator.run_feature_plan", _fake_run_feature_plan)
    monkeypatch.setattr("agents.ticket_generator.get_llm_provider", lambda: _FakeLLMProvider())

    test_client = TestClient(app)
    response = test_client.post(
        "/tickets", json={"repo_id": "repo", "feature_description": "Add a field", "top_k": 3}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["plan"] == "1. Do X."
    assert body["risks"] == ["Some risk."]
    assert body["affected_modules"][0]["file_path"] == "a.py"
    assert body["epics"][0]["title"] == "Epic 1"
    assert body["epics"][0]["stories"][0]["tasks"][0]["title"] == "Task 1"

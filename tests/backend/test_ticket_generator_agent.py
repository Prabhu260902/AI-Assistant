import json

from graphs.ticket_generator import run_generate_tickets
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
        "plan": "1. Do X.\n2. Do Y.",
        "affected_modules": [
            AffectedModule(file_path="a.py", reason="directly relevant", fan_in=1, has_api_endpoint=False)
        ],
        "risks": ["Some risk."],
    }


class _FakeLLMProvider:
    def __init__(self, response: str):
        self._response = response

    def complete(self, prompt: str, json_mode: bool = False) -> str:
        return self._response


def test_ticket_generator_parses_valid_json(monkeypatch):
    monkeypatch.setattr("agents.ticket_generator.run_feature_plan", _fake_run_feature_plan)
    monkeypatch.setattr("agents.ticket_generator.get_llm_provider", lambda: _FakeLLMProvider(VALID_JSON))

    state = run_generate_tickets("repo", "feature", top_k=3)

    assert state["plan"] == "1. Do X.\n2. Do Y."
    assert len(state["epics"]) == 1
    assert state["epics"][0].title == "Epic 1"
    assert state["epics"][0].stories[0].tasks[0].title == "Task 1"
    assert state["epics"][0].stories[0].acceptance_criteria == ["AC1"]


def test_ticket_generator_handles_markdown_fenced_json(monkeypatch):
    monkeypatch.setattr("agents.ticket_generator.run_feature_plan", _fake_run_feature_plan)
    fenced = f"```json\n{VALID_JSON}\n```"
    monkeypatch.setattr("agents.ticket_generator.get_llm_provider", lambda: _FakeLLMProvider(fenced))

    state = run_generate_tickets("repo", "feature", top_k=3)

    assert len(state["epics"]) == 1
    assert state["epics"][0].title == "Epic 1"


def test_ticket_generator_falls_back_gracefully_on_malformed_json(monkeypatch):
    monkeypatch.setattr("agents.ticket_generator.run_feature_plan", _fake_run_feature_plan)
    monkeypatch.setattr("agents.ticket_generator.get_llm_provider", lambda: _FakeLLMProvider("not json at all"))

    state = run_generate_tickets("repo", "feature", top_k=3)

    assert len(state["epics"]) == 1
    assert "not json at all" in state["epics"][0].stories[0].description

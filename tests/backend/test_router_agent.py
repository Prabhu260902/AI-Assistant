import json

import pytest

from graphs.router import run_copilot
from services.git_diff import GitDiffError


class _FakeLLMProvider:
    def __init__(self, response: str):
        self._response = response

    def complete(self, prompt: str, json_mode: bool = False) -> str:
        return self._response


def _classification(intent: str, base_ref=None, head_ref=None) -> str:
    return json.dumps({"intent": intent, "base_ref": base_ref, "head_ref": head_ref})


@pytest.mark.parametrize(
    "intent, target_name",
    [
        ("search", "run_code_search"),
        ("architecture", "run_architecture_explanation"),
        ("plan", "run_feature_plan"),
        ("tickets", "run_generate_tickets"),
        ("implement", "run_implementation"),
    ],
)
def test_router_dispatches_each_intent_to_its_own_agent(monkeypatch, intent, target_name):
    monkeypatch.setattr("agents.router.get_llm_provider", lambda: _FakeLLMProvider(_classification(intent)))

    calls = []

    def _fake_target(repo_id, message, top_k):
        calls.append((repo_id, message, top_k))
        return {"marker": target_name}

    monkeypatch.setattr(f"agents.router.{target_name}", _fake_target)

    state = run_copilot("repo-x", "some message", top_k=7)

    assert state["intent"] == intent
    assert state["result"] == {"marker": target_name}
    assert calls == [("repo-x", "some message", 7)]


def test_router_falls_back_to_search_on_malformed_llm_response(monkeypatch):
    monkeypatch.setattr("agents.router.get_llm_provider", lambda: _FakeLLMProvider("not json at all"))

    calls = []
    monkeypatch.setattr(
        "agents.router.run_code_search",
        lambda repo_id, message, top_k: calls.append((repo_id, message, top_k)) or {"answer": "ok"},
    )

    state = run_copilot("repo-x", "hello there", top_k=5)

    assert state["intent"] == "search"
    assert calls == [("repo-x", "hello there", 5)]


def test_router_review_defaults_refs_when_not_extracted(monkeypatch):
    monkeypatch.setattr("agents.router.get_llm_provider", lambda: _FakeLLMProvider(_classification("review")))

    calls = []
    monkeypatch.setattr(
        "agents.router.run_pr_review",
        lambda repo_id, base_ref, head_ref: calls.append((repo_id, base_ref, head_ref)) or {"summary": "ok"},
    )

    run_copilot("repo-x", "review my changes", top_k=5)

    assert calls == [("repo-x", "main", "HEAD")]


def test_router_review_uses_extracted_refs(monkeypatch):
    monkeypatch.setattr(
        "agents.router.get_llm_provider",
        lambda: _FakeLLMProvider(_classification("review", base_ref="develop", head_ref="my-feature")),
    )

    calls = []
    monkeypatch.setattr(
        "agents.router.run_pr_review",
        lambda repo_id, base_ref, head_ref: calls.append((repo_id, base_ref, head_ref)) or {"summary": "ok"},
    )

    run_copilot("repo-x", "review develop..my-feature", top_k=5)

    assert calls == [("repo-x", "develop", "my-feature")]


def test_router_lets_git_diff_error_propagate(monkeypatch):
    monkeypatch.setattr("agents.router.get_llm_provider", lambda: _FakeLLMProvider(_classification("review")))

    def _raise(repo_id, base_ref, head_ref):
        raise GitDiffError("bad ref")

    monkeypatch.setattr("agents.router.run_pr_review", _raise)

    with pytest.raises(GitDiffError):
        run_copilot("repo-x", "review this", top_k=5)

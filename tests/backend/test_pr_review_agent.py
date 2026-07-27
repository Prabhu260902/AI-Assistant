import json
import subprocess

import pytest

from graphs.pr_review import run_pr_review


def _run(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


class _FakeLLMProvider:
    def __init__(self, response: str):
        self._response = response

    def complete(self, prompt: str, json_mode: bool = False) -> str:
        return self._response


@pytest.fixture
def git_repo_with_changes(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    _run(repo, "init", "-q")
    _run(repo, "config", "user.email", "test@test.com")
    _run(repo, "config", "user.name", "Test")
    (repo / "app.py").write_text("x = 1\n")
    _run(repo, "add", "app.py")
    _run(repo, "commit", "-q", "-m", "initial")
    base_branch = subprocess.run(
        ["git", "branch", "--show-current"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()

    _run(repo, "checkout", "-q", "-b", "feature")
    (repo / "app.py").write_text('x = 1\napi_key = "sk-abcdefghij1234567890"\n')
    _run(repo, "add", "app.py")
    _run(repo, "commit", "-q", "-m", "add key")
    _run(repo, "checkout", "-q", base_branch)

    monkeypatch.setattr("agents.pr_review.get_repo_source", lambda repo_id: str(repo))
    return repo, base_branch


VALID_JSON = json.dumps(
    {
        "summary": "Adds a hardcoded key.",
        "findings": [
            {
                "category": "correctness",
                "severity": "low",
                "file_path": "app.py",
                "line": 2,
                "description": "Consider using a constant name convention.",
            }
        ],
    }
)


def test_pr_review_includes_grounded_findings_before_llm_findings(git_repo_with_changes, monkeypatch):
    repo, base_branch = git_repo_with_changes
    monkeypatch.setattr("agents.pr_review.get_llm_provider", lambda: _FakeLLMProvider(VALID_JSON))

    state = run_pr_review("any-repo-id", base_branch, "feature")

    categories = [f.category for f in state["findings"]]
    assert "security" in categories  # grounded secret-scan finding
    assert "correctness" in categories  # LLM finding
    assert state["summary"] == "Adds a hardcoded key."


def test_pr_review_falls_back_to_grounded_findings_on_malformed_llm_response(git_repo_with_changes, monkeypatch):
    repo, base_branch = git_repo_with_changes
    monkeypatch.setattr("agents.pr_review.get_llm_provider", lambda: _FakeLLMProvider("not json at all"))

    state = run_pr_review("any-repo-id", base_branch, "feature")

    # both grounded checks fire here (a secret was added, and app.py has no
    # matching test file) — the LLM's malformed response should only cost
    # us its own additional findings, not the grounded ones already found.
    categories = {f.category for f in state["findings"]}
    assert categories == {"security", "test_coverage"}
    assert "could not be parsed" in state["summary"]


def test_pr_review_on_unknown_repo_reports_no_changes(monkeypatch):
    monkeypatch.setattr("agents.pr_review.get_repo_source", lambda repo_id: None)

    state = run_pr_review("no-such-repo", "main", "feature")

    assert state["findings"] == []
    assert "No changes found" in state["summary"]

import json
import subprocess

from fastapi.testclient import TestClient

from main import app


def _run(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


class _FakeLLMProvider:
    def complete(self, prompt: str, json_mode: bool = False) -> str:
        return json.dumps({"summary": "Looks fine overall.", "findings": []})


def test_review_endpoint_returns_summary_and_findings(tmp_path, monkeypatch):
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
    (repo / "app.py").write_text("x = 1\ny = 2\n")
    _run(repo, "add", "app.py")
    _run(repo, "commit", "-q", "-m", "add y")
    _run(repo, "checkout", "-q", base_branch)

    monkeypatch.setattr("agents.pr_review.get_repo_source", lambda repo_id: str(repo))
    monkeypatch.setattr("agents.pr_review.get_llm_provider", lambda: _FakeLLMProvider())

    client = TestClient(app)
    response = client.post(
        "/review", json={"repo_id": "review-endpoint-repo", "base_ref": base_branch, "head_ref": "feature"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["summary"] == "Looks fine overall."


def test_review_endpoint_returns_400_for_unknown_ref(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    _run(repo, "init", "-q")
    _run(repo, "config", "user.email", "test@test.com")
    _run(repo, "config", "user.name", "Test")
    (repo / "app.py").write_text("x = 1\n")
    _run(repo, "add", "app.py")
    _run(repo, "commit", "-q", "-m", "initial")

    monkeypatch.setattr("agents.pr_review.get_repo_source", lambda repo_id: str(repo))

    client = TestClient(app)
    response = client.post(
        "/review", json={"repo_id": "review-endpoint-repo-2", "base_ref": "HEAD", "head_ref": "no-such-ref"}
    )

    assert response.status_code == 400

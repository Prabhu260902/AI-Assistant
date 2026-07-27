import subprocess

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from main import app
from services.hybrid_search import SearchResult
from services.models import Base, Repository


def _run(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


class _FakeLLMProvider:
    def __init__(self, response: str):
        self._response = response

    def complete(self, prompt: str, json_mode: bool = False) -> str:
        return self._response


def _seed_sqlite_repo(monkeypatch, repo_id: str, source: str):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    monkeypatch.setattr("services.db.get_engine", lambda: engine)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Repository(repo_id=repo_id, source=source))
        session.commit()


def test_implement_endpoint_returns_proposed_changes(tmp_path, monkeypatch):
    (tmp_path / "file.py").write_text("original content\n")
    _seed_sqlite_repo(monkeypatch, "implement-endpoint-repo", str(tmp_path))

    monkeypatch.setattr(
        "agents.implementation.run_feature_plan",
        lambda repo_id, feature_description, top_k: {
            "plan": "1. Update file.py.",
            "risks": ["Some risk."],
            "context_results": [
                SearchResult(
                    chunk_id="a",
                    content="original content",
                    file_path="file.py",
                    start_line=1,
                    end_line=1,
                    language="python",
                    score=1.0,
                )
            ],
        },
    )
    monkeypatch.setattr("agents.implementation.get_llm_provider", lambda: _FakeLLMProvider("new content\n"))

    client = TestClient(app)
    response = client.post(
        "/implement", json={"repo_id": "implement-endpoint-repo", "feature_description": "Change file.py", "top_k": 3}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["plan"] == "1. Update file.py."
    assert len(body["proposed_changes"]) == 1
    assert body["proposed_changes"][0]["file_path"] == "file.py"
    assert body["proposed_changes"][0]["new_content"] == "new content\n"
    # dry run: nothing written to disk
    assert (tmp_path / "file.py").read_text() == "original content\n"


def test_implement_apply_endpoint_writes_files_on_new_branch(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    _run(repo, "init", "-q")
    _run(repo, "config", "user.email", "test@test.com")
    _run(repo, "config", "user.name", "Test")
    (repo / "file.py").write_text("original content\n")
    _run(repo, "add", "file.py")
    _run(repo, "commit", "-q", "-m", "initial")

    _seed_sqlite_repo(monkeypatch, "apply-endpoint-repo", str(repo))

    client = TestClient(app)
    response = client.post(
        "/implement/apply",
        json={
            "repo_id": "apply-endpoint-repo",
            "changes": [{"file_path": "file.py", "new_content": "new content\n"}],
            "branch_name": "allease/endpoint-test",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["branch"] == "allease/endpoint-test"
    assert body["files_written"] == ["file.py"]
    assert (repo / "file.py").read_text() == "new content\n"


def test_implement_apply_endpoint_returns_409_on_dirty_tree(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    _run(repo, "init", "-q")
    _run(repo, "config", "user.email", "test@test.com")
    _run(repo, "config", "user.name", "Test")
    (repo / "file.py").write_text("original content\n")
    _run(repo, "add", "file.py")
    _run(repo, "commit", "-q", "-m", "initial")
    (repo / "file.py").write_text("uncommitted edit\n")

    _seed_sqlite_repo(monkeypatch, "dirty-apply-repo", str(repo))

    client = TestClient(app)
    response = client.post(
        "/implement/apply",
        json={
            "repo_id": "dirty-apply-repo",
            "changes": [{"file_path": "file.py", "new_content": "new content\n"}],
            "branch_name": "allease/dirty-test",
        },
    )

    assert response.status_code == 409


def test_implement_apply_endpoint_returns_404_for_unknown_repo(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    monkeypatch.setattr("services.db.get_engine", lambda: engine)
    Base.metadata.create_all(engine)

    client = TestClient(app)
    response = client.post(
        "/implement/apply",
        json={"repo_id": "no-such-repo", "changes": [], "branch_name": "allease/x"},
    )

    assert response.status_code == 404

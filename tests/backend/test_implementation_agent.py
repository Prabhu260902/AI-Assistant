import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from graphs.implementation import run_implementation
from services.hybrid_search import SearchResult
from services.models import Base, Repository


class _FakeLLMProvider:
    def __init__(self, response: str):
        self._response = response

    def complete(self, prompt: str, json_mode: bool = False) -> str:
        return self._response


def _fake_context_result(file_path: str) -> SearchResult:
    return SearchResult(
        chunk_id="a", content="original content", file_path=file_path, start_line=1, end_line=1, language="python", score=1.0
    )


@pytest.fixture
def repo_with_files(tmp_path, monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    monkeypatch.setattr("services.db.get_engine", lambda: engine)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Repository(repo_id="impl-test-repo", source=str(tmp_path)))
        session.commit()

    (tmp_path / "file.py").write_text("original content\n")
    return tmp_path


def _fake_run_feature_plan(file_paths):
    def _inner(repo_id, feature_description, top_k):
        return {
            "plan": "1. Update file.py.",
            "risks": ["Some risk."],
            "context_results": [_fake_context_result(fp) for fp in file_paths],
        }

    return _inner


def test_generate_code_produces_diff_for_changed_file(repo_with_files, monkeypatch):
    monkeypatch.setattr("agents.implementation.run_feature_plan", _fake_run_feature_plan(["file.py"]))
    monkeypatch.setattr(
        "agents.implementation.get_llm_provider", lambda: _FakeLLMProvider("new content\n")
    )

    state = run_implementation("impl-test-repo", "Change file.py", top_k=3)

    assert state["plan"] == "1. Update file.py."
    assert len(state["proposed_changes"]) == 1
    change = state["proposed_changes"][0]
    assert change.file_path == "file.py"
    assert change.new_content == "new content\n"
    assert "-original content" in change.diff
    assert "+new content" in change.diff


def test_generate_code_strips_markdown_fences(repo_with_files, monkeypatch):
    monkeypatch.setattr("agents.implementation.run_feature_plan", _fake_run_feature_plan(["file.py"]))
    monkeypatch.setattr(
        "agents.implementation.get_llm_provider",
        lambda: _FakeLLMProvider("```python\nnew content\n```"),
    )

    state = run_implementation("impl-test-repo", "Change file.py", top_k=3)

    assert state["proposed_changes"][0].new_content == "new content\n"


def test_generate_code_preserves_internal_code_fences(repo_with_files, monkeypatch):
    """Regression test: a markdown-style regenerated file's own embedded
    ``` blocks must survive — only a fence wrapping the WHOLE response
    should ever be stripped. An earlier version stripped every ``` line via
    regex and silently corrupted files like README.md that legitimately
    contain their own code blocks."""
    monkeypatch.setattr("agents.implementation.run_feature_plan", _fake_run_feature_plan(["file.py"]))
    content_with_internal_fences = "# Title\n\n```bash\ncd backend\nrun me\n```\n\nmore text\n"
    monkeypatch.setattr(
        "agents.implementation.get_llm_provider", lambda: _FakeLLMProvider(content_with_internal_fences)
    )

    state = run_implementation("impl-test-repo", "Change file.py", top_k=3)

    assert state["proposed_changes"][0].new_content == content_with_internal_fences


def test_generate_code_skips_unchanged_files(repo_with_files, monkeypatch):
    monkeypatch.setattr("agents.implementation.run_feature_plan", _fake_run_feature_plan(["file.py"]))
    monkeypatch.setattr(
        "agents.implementation.get_llm_provider", lambda: _FakeLLMProvider("original content\n")
    )

    state = run_implementation("impl-test-repo", "Change file.py", top_k=3)

    assert state["proposed_changes"] == []


def test_generate_code_skips_missing_file_gracefully(repo_with_files, monkeypatch):
    monkeypatch.setattr("agents.implementation.run_feature_plan", _fake_run_feature_plan(["does_not_exist.py"]))
    monkeypatch.setattr("agents.implementation.get_llm_provider", lambda: _FakeLLMProvider("whatever"))

    state = run_implementation("impl-test-repo", "Change something", top_k=3)

    assert state["proposed_changes"] == []


def test_generate_code_on_unknown_repo_returns_no_changes(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    monkeypatch.setattr("services.db.get_engine", lambda: engine)
    Base.metadata.create_all(engine)

    monkeypatch.setattr("agents.implementation.run_feature_plan", _fake_run_feature_plan(["file.py"]))
    monkeypatch.setattr("agents.implementation.get_llm_provider", lambda: _FakeLLMProvider("x"))

    state = run_implementation("no-such-repo", "Change something", top_k=3)

    assert state["proposed_changes"] == []

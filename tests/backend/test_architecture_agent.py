import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from graphs.architecture import run_architecture_explanation
from services.hybrid_search import SearchResult
from services.models import ApiEndpoint, Base, Call, File, Repository, Symbol


class _FakeLLMProvider:
    def __init__(self, response: str):
        self._response = response

    def complete(self, prompt: str, json_mode: bool = False) -> str:
        return self._response


@pytest.fixture
def seeded_repo(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    monkeypatch.setattr("services.db.get_engine", lambda: engine)
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        repo = Repository(repo_id="arch-agent-repo", source="/tmp/x")
        session.add(repo)
        session.flush()

        f_hcps = File(repository_id=repo.id, file_path="backend/routers/hcps.py", language="python")
        session.add(f_hcps)
        session.flush()

        sym_create = Symbol(file_id=f_hcps.id, name="create_hcp", kind="Function", start_line=10, end_line=15)
        sym_helper = Symbol(file_id=f_hcps.id, name="validate_hcp", kind="Function", start_line=20, end_line=25)
        session.add_all([sym_create, sym_helper])
        session.flush()

        session.add(
            ApiEndpoint(
                file_id=f_hcps.id,
                method="POST",
                path="/hcps",
                handler_symbol_id=sym_create.id,
                framework_hint="fastapi_flask",
                start_line=10,
            )
        )
        session.add(
            Call(
                file_id=f_hcps.id,
                caller_symbol_id=sym_create.id,
                callee_name="validate_hcp",
                callee_symbol_id=sym_helper.id,
                start_line=11,
            )
        )
        session.commit()

    return engine


def _fake_search_repo(hit_file_path: str, hit_line: int):
    def _inner(repo_id, query, top_k):
        return [
            SearchResult(
                chunk_id="a",
                content="def create_hcp(...): ...",
                file_path=hit_file_path,
                start_line=hit_line,
                end_line=hit_line,
                language="python",
                score=1.0,
            )
        ]

    return _inner


def test_architecture_agent_builds_graph_and_explains(seeded_repo, monkeypatch):
    monkeypatch.setattr(
        "agents.architecture.search_repo", _fake_search_repo("backend/routers/hcps.py", 12)
    )
    monkeypatch.setattr(
        "agents.architecture.get_llm_provider", lambda: _FakeLLMProvider("This endpoint validates the HCP.")
    )

    state = run_architecture_explanation("arch-agent-repo", "How does creating an HCP work?")

    assert state["explanation"] == "This endpoint validates the HCP."
    assert "flowchart TD" in state["mermaid_diagram"]
    assert state["flow_graph"] is not None
    assert any(n.name == "create_hcp" for n in state["flow_graph"].nodes)
    assert any(n.name == "validate_hcp" for n in state["flow_graph"].nodes)


def test_architecture_agent_skips_llm_call_when_no_search_results(seeded_repo, monkeypatch):
    monkeypatch.setattr("agents.architecture.search_repo", lambda repo_id, query, top_k: [])

    def _fail_if_called():
        raise AssertionError("LLM should not be called when there are no search results")

    monkeypatch.setattr("agents.architecture.get_llm_provider", _fail_if_called)

    state = run_architecture_explanation("arch-agent-repo", "anything")

    assert state["flow_graph"] is None
    assert "Could not find" in state["explanation"]


def test_architecture_agent_skips_llm_call_when_start_point_unresolvable(seeded_repo, monkeypatch):
    # a hit pointing at a line with no containing symbol
    monkeypatch.setattr(
        "agents.architecture.search_repo", _fake_search_repo("backend/routers/hcps.py", 999)
    )

    def _fail_if_called():
        raise AssertionError("LLM should not be called when no start point resolves")

    monkeypatch.setattr("agents.architecture.get_llm_provider", _fail_if_called)

    state = run_architecture_explanation("arch-agent-repo", "anything")

    assert state["flow_graph"] is None


def test_architecture_agent_falls_through_to_next_hit_when_first_is_unresolvable(seeded_repo, monkeypatch):
    """Regression test: caught by real-repo verification against hcp-crm —
    the top hybrid-search hit was README.md (no Postgres symbols at all,
    since Phase 3 only extracts symbols from code), and the agent gave up
    instead of trying the next-ranked hit."""

    def _fake_search_repo(repo_id, query, top_k):
        return [
            SearchResult(
                chunk_id="a",
                content="# Title",
                file_path="README.md",
                start_line=1,
                end_line=10,
                language="markdown",
                score=1.0,
            ),
            SearchResult(
                chunk_id="b",
                content="def create_hcp(...): ...",
                file_path="backend/routers/hcps.py",
                start_line=12,
                end_line=12,
                language="python",
                score=0.9,
            ),
        ]

    monkeypatch.setattr("agents.architecture.search_repo", _fake_search_repo)
    monkeypatch.setattr("agents.architecture.get_llm_provider", lambda: _FakeLLMProvider("Explanation."))

    state = run_architecture_explanation("arch-agent-repo", "How does creating an HCP work?")

    assert state["flow_graph"] is not None
    assert any(n.name == "create_hcp" for n in state["flow_graph"].nodes)

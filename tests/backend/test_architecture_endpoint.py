from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from main import app
from services.hybrid_search import SearchResult
from services.models import ApiEndpoint, Base, Call, File, Repository, Symbol


class _FakeLLMProvider:
    def complete(self, prompt: str, json_mode: bool = False) -> str:
        return "This endpoint creates an HCP and validates it."


def test_architecture_endpoint_returns_explanation_and_diagram(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    monkeypatch.setattr("services.db.get_engine", lambda: engine)
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        repo = Repository(repo_id="arch-endpoint-repo", source="/tmp/x")
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

    monkeypatch.setattr(
        "agents.architecture.search_repo",
        lambda repo_id, query, top_k: [
            SearchResult(
                chunk_id="a",
                content="def create_hcp(...): ...",
                file_path="backend/routers/hcps.py",
                start_line=12,
                end_line=12,
                language="python",
                score=1.0,
            )
        ],
    )
    monkeypatch.setattr("agents.architecture.get_llm_provider", lambda: _FakeLLMProvider())

    client = TestClient(app)
    response = client.post(
        "/architecture",
        json={"repo_id": "arch-endpoint-repo", "query": "How does creating an HCP work?", "top_k": 3},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["explanation"] == "This endpoint creates an HCP and validates it."
    assert "flowchart TD" in body["mermaid_diagram"]
    assert any(n["name"] == "create_hcp" for n in body["nodes"])
    assert any(n["name"] == "validate_hcp" for n in body["nodes"])

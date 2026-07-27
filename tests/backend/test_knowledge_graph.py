import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from services.knowledge_graph import build_knowledge_graph, extract_file_graph
from services.models import ApiEndpoint, Call, File, Repository, Symbol


# --- pure extraction tests (no DB) ---------------------------------------


def test_python_imports_and_symbols_are_extracted():
    src = "import os\nfrom typing import Optional\n\ndef helper(x):\n    return x\n"

    graph = extract_file_graph(src, "python")

    assert [i.raw_source for i in graph.imports] == ["import os", "from typing import Optional"]
    assert graph.imports[0].module_path == "os"
    assert graph.imports[1].module_path == "typing"
    assert any(s.name == "helper" and s.kind == "Function" for s in graph.symbols)


def test_python_call_is_extracted():
    src = "def helper(x):\n    return x\n\ndef main():\n    return helper(1)\n"

    graph = extract_file_graph(src, "python")

    assert any(c.callee_name == "helper" for c in graph.calls)


def test_python_fastapi_style_endpoint_is_detected():
    src = (
        "from fastapi import APIRouter\n"
        "router = APIRouter()\n\n"
        '@router.get("/hcps")\n'
        "def list_hcps():\n"
        "    return []\n"
    )

    graph = extract_file_graph(src, "python")

    assert len(graph.endpoints) == 1
    endpoint = graph.endpoints[0]
    assert endpoint.method == "GET"
    assert endpoint.path == "/hcps"
    assert endpoint.handler_name == "list_hcps"
    assert endpoint.framework_hint == "fastapi_flask"


def test_unrelated_python_decorator_is_not_mistaken_for_endpoint():
    src = '@app.on_event("startup")\nasync def on_startup():\n    pass\n'

    graph = extract_file_graph(src, "python")

    assert graph.endpoints == []


def test_js_express_style_endpoint_is_detected():
    src = 'app.get("/hcps", listHcps);\n'

    graph = extract_file_graph(src, "javascript")

    assert len(graph.endpoints) == 1
    endpoint = graph.endpoints[0]
    assert endpoint.method == "GET"
    assert endpoint.path == "/hcps"
    assert endpoint.handler_name == "listHcps"
    assert endpoint.framework_hint == "express"


def test_unrelated_js_call_is_not_mistaken_for_endpoint():
    src = 'logger.info("server started");\n'

    graph = extract_file_graph(src, "javascript")

    assert graph.endpoints == []


def test_unmapped_language_returns_empty_graph():
    graph = extract_file_graph("# just some notes\n", "markdown")

    assert graph.calls == []
    assert graph.endpoints == []


# --- persistence tests (in-memory SQLite, no Docker/Postgres) ------------


@pytest.fixture
def sqlite_engine(monkeypatch, tmp_path):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    monkeypatch.setattr("services.db.get_engine", lambda: engine)

    repo_dir = tmp_path / "fixture-repo"
    (repo_dir / "app").mkdir(parents=True)
    (repo_dir / "app" / "main.py").write_text(
        "from fastapi import APIRouter\n"
        "router = APIRouter()\n\n"
        "def helper(x):\n"
        "    return x\n\n"
        '@router.get("/items")\n'
        "def list_items():\n"
        "    return helper(1)\n"
    )
    return engine, repo_dir


def test_build_knowledge_graph_persists_expected_rows(sqlite_engine):
    engine, repo_dir = sqlite_engine

    summary = build_knowledge_graph(str(repo_dir), repo_id="fixture-repo")

    assert summary.files == 1
    assert summary.symbols >= 2  # helper + list_items
    assert summary.imports == 1
    assert summary.calls >= 1
    assert summary.endpoints == 1

    with Session(engine) as session:
        repo = session.execute(select(Repository).where(Repository.repo_id == "fixture-repo")).scalar_one()
        assert repo is not None

        endpoint = session.execute(select(ApiEndpoint)).scalar_one()
        assert endpoint.method == "GET"
        assert endpoint.path == "/items"

        helper_symbol = session.execute(select(Symbol).where(Symbol.name == "helper")).scalar_one()
        call = session.execute(select(Call).where(Call.callee_name == "helper")).scalar_one()
        assert call.callee_symbol_id == helper_symbol.id

        list_items_symbol = session.execute(select(Symbol).where(Symbol.name == "list_items")).scalar_one()
        assert endpoint.handler_symbol_id == list_items_symbol.id


def test_build_knowledge_graph_is_idempotent_on_rerun(sqlite_engine):
    engine, repo_dir = sqlite_engine

    build_knowledge_graph(str(repo_dir), repo_id="fixture-repo")
    build_knowledge_graph(str(repo_dir), repo_id="fixture-repo")

    with Session(engine) as session:
        repo_count = len(session.execute(select(Repository)).scalars().all())
        file_count = len(session.execute(select(File)).scalars().all())
        symbol_count = len(session.execute(select(Symbol)).scalars().all())

    assert repo_count == 1
    assert file_count == 1
    assert symbol_count >= 2

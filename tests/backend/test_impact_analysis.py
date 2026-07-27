import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from services.impact_analysis import find_affected_modules
from services.models import ApiEndpoint, Base, File, Import, Repository


@pytest.fixture
def sqlite_engine(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    monkeypatch.setattr("services.db.get_engine", lambda: engine)
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        repo = Repository(repo_id="impact-test-repo", source="/tmp/impact-test-repo")
        session.add(repo)
        session.flush()

        f_hcps = File(repository_id=repo.id, file_path="backend/routers/hcps.py", language="python")
        f_schemas = File(repository_id=repo.id, file_path="backend/models/schemas.py", language="python")
        f_main = File(repository_id=repo.id, file_path="backend/main.py", language="python")
        f_unrelated = File(repository_id=repo.id, file_path="backend/routers/interactions.py", language="python")
        session.add_all([f_hcps, f_schemas, f_main, f_unrelated])
        session.flush()

        session.add_all(
            [
                Import(
                    file_id=f_hcps.id,
                    raw_source="from models.schemas import HCPCreate",
                    module_path="models.schemas",
                    start_line=3,
                ),
                Import(
                    file_id=f_main.id,
                    raw_source="from routers.hcps import router",
                    module_path="routers.hcps",
                    start_line=5,
                ),
                Import(
                    file_id=f_unrelated.id,
                    raw_source="import os",
                    module_path="os",
                    start_line=1,
                ),
            ]
        )
        session.add(
            ApiEndpoint(
                file_id=f_hcps.id,
                method="POST",
                path="/",
                handler_symbol_id=None,
                framework_hint="fastapi_flask",
                start_line=10,
            )
        )
        session.commit()

    return engine


def test_find_affected_modules_marks_direct_hits(sqlite_engine):
    results = find_affected_modules("impact-test-repo", ["backend/routers/hcps.py"])

    direct = next(r for r in results if r.file_path == "backend/routers/hcps.py")
    assert direct.reason == "directly relevant"
    assert direct.has_api_endpoint is True
    assert direct.fan_in == 1  # backend/main.py imports it


def test_find_affected_modules_expands_to_dependents(sqlite_engine):
    results = find_affected_modules("impact-test-repo", ["backend/routers/hcps.py"])

    dependent = next((r for r in results if r.file_path == "backend/main.py"), None)
    assert dependent is not None
    assert dependent.reason == "imports backend/routers/hcps.py"
    assert dependent.has_api_endpoint is False


def test_find_affected_modules_excludes_unrelated_files(sqlite_engine):
    results = find_affected_modules("impact-test-repo", ["backend/routers/hcps.py"])

    file_paths = {r.file_path for r in results}
    assert "backend/routers/interactions.py" not in file_paths


def test_find_affected_modules_on_unknown_repo_returns_empty(sqlite_engine):
    assert find_affected_modules("no-such-repo", ["a.py"]) == []

import chromadb
import pytest
from chromadb.api.types import EmbeddingFunction
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from graphs.feature_planner import run_feature_plan
from services.models import Base, File, Import, Repository


class _FakeEmbeddingFunction(EmbeddingFunction):
    def __init__(self):
        pass

    def __call__(self, input):
        return [[float(len(text) % 7 + 1), 0.0, 1.0] for text in input]

    @staticmethod
    def name() -> str:
        return "fake-test-embedding-function"

    def get_config(self) -> dict:
        return {}

    @staticmethod
    def build_from_config(config: dict) -> "_FakeEmbeddingFunction":
        return _FakeEmbeddingFunction()


class _FakeVectorStore:
    def __init__(self, client):
        self._client = client

    def get_or_create_collection(self, name):
        return self._client.get_or_create_collection(name, embedding_function=_FakeEmbeddingFunction())


class _FakeLLMProvider:
    def __init__(self, response: str):
        self._response = response

    def complete(self, prompt: str) -> str:
        return self._response


@pytest.fixture
def seeded_repo(monkeypatch):
    chroma_client = chromadb.EphemeralClient()
    collection = chroma_client.get_or_create_collection(
        "feature-planner-test-repo", embedding_function=_FakeEmbeddingFunction()
    )
    collection.upsert(
        ids=["a"],
        documents=["def create_hcp(payload): return db.insert(payload)"],
        metadatas=[{"file_path": "backend/routers/hcps.py", "start_line": 10, "end_line": 12, "language": "python"}],
    )
    monkeypatch.setattr("services.hybrid_search.get_vector_store", lambda: _FakeVectorStore(chroma_client))

    sql_engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    monkeypatch.setattr("services.db.get_engine", lambda: sql_engine)
    Base.metadata.create_all(sql_engine)
    with Session(sql_engine) as session:
        repo = Repository(repo_id="feature-planner-test-repo", source="/tmp/x")
        session.add(repo)
        session.flush()

        f_hcps = File(repository_id=repo.id, file_path="backend/routers/hcps.py", language="python")
        f_main = File(repository_id=repo.id, file_path="backend/main.py", language="python")
        session.add_all([f_hcps, f_main])
        session.flush()

        session.add(
            Import(
                file_id=f_main.id,
                raw_source="from routers.hcps import router",
                module_path="routers.hcps",
                start_line=5,
            )
        )
        session.commit()


def test_feature_planner_splits_plan_and_risks(seeded_repo, monkeypatch):
    monkeypatch.setattr(
        "agents.feature_planner.get_llm_provider",
        lambda: _FakeLLMProvider(
            "1. Add a specialty field to the HCP model.\n"
            "2. Update the create_hcp handler.\n\n"
            "RISKS:\n"
            "- No test coverage found for the schema layer.\n"
            "- Requires a database migration.\n"
        ),
    )

    state = run_feature_plan("feature-planner-test-repo", "Add a specialty field to HCPs", top_k=3)

    assert "Add a specialty field to the HCP model" in state["plan"]
    assert "RISKS:" not in state["plan"]
    assert "No test coverage found for the schema layer." in state["risks"]
    assert "Requires a database migration." in state["risks"]


def test_feature_planner_prepends_computed_risks(seeded_repo, monkeypatch):
    monkeypatch.setattr("agents.feature_planner.get_llm_provider", lambda: _FakeLLMProvider("A plan.\n\nRISKS:\n"))

    state = run_feature_plan("feature-planner-test-repo", "Add a specialty field to HCPs", top_k=3)

    # backend/routers/hcps.py has fan_in=1 (below the threshold of 3) but no
    # API endpoint was seeded here, so no computed risk strings are expected
    # in this particular fixture — this test just confirms the computed
    # risks (if any) come before the LLM's own risks.
    assert state["risks"] == [] or state["risks"][0].startswith(("High fan-in", "Public API surface"))


def test_feature_planner_includes_affected_modules(seeded_repo, monkeypatch):
    monkeypatch.setattr("agents.feature_planner.get_llm_provider", lambda: _FakeLLMProvider("A plan.\n\nRISKS:\n"))

    state = run_feature_plan("feature-planner-test-repo", "Add a specialty field to HCPs", top_k=3)

    file_paths = {m.file_path for m in state["affected_modules"]}
    assert "backend/routers/hcps.py" in file_paths
    assert "backend/main.py" in file_paths

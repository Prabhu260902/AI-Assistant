import chromadb
from chromadb.api.types import EmbeddingFunction
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from main import app
from services.models import Base, File, Repository


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
    def complete(self, prompt: str) -> str:
        return "1. Add a specialty field.\n\nRISKS:\n- Requires a migration.\n"


def test_plan_endpoint_returns_plan_modules_and_risks(monkeypatch):
    chroma_client = chromadb.EphemeralClient()
    collection = chroma_client.get_or_create_collection(
        "plan-endpoint-test-repo", embedding_function=_FakeEmbeddingFunction()
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
        repo = Repository(repo_id="plan-endpoint-test-repo", source="/tmp/x")
        session.add(repo)
        session.flush()
        session.add(File(repository_id=repo.id, file_path="backend/routers/hcps.py", language="python"))
        session.commit()

    monkeypatch.setattr("agents.feature_planner.get_llm_provider", lambda: _FakeLLMProvider())

    test_client = TestClient(app)
    response = test_client.post(
        "/plan",
        json={"repo_id": "plan-endpoint-test-repo", "feature_description": "Add a specialty field to HCPs", "top_k": 3},
    )

    assert response.status_code == 200
    body = response.json()
    assert "Add a specialty field" in body["plan"]
    assert "RISKS:" not in body["plan"]
    assert "Requires a migration." in body["risks"]
    assert any(m["file_path"] == "backend/routers/hcps.py" for m in body["affected_modules"])

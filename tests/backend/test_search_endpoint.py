import chromadb
from chromadb.api.types import EmbeddingFunction
from fastapi.testclient import TestClient

from main import app


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
        return "HCPs are created via create_hcp [1]."


def test_search_endpoint_returns_answer_and_citations(monkeypatch):
    client = chromadb.EphemeralClient()
    collection = client.get_or_create_collection("search-endpoint-test-repo", embedding_function=_FakeEmbeddingFunction())
    collection.upsert(
        ids=["a"],
        documents=["def create_hcp(payload): return db.insert(payload)"],
        metadatas=[{"file_path": "backend/routers/hcps.py", "start_line": 10, "end_line": 12, "language": "python"}],
    )
    monkeypatch.setattr("services.hybrid_search.get_vector_store", lambda: _FakeVectorStore(client))
    monkeypatch.setattr("agents.code_search.get_llm_provider", lambda: _FakeLLMProvider())

    test_client = TestClient(app)
    response = test_client.post(
        "/search", json={"repo_id": "search-endpoint-test-repo", "query": "how do you create an hcp?", "top_k": 3}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["answer"] == "HCPs are created via create_hcp [1]."
    assert body["citations"] == [
        {"file_path": "backend/routers/hcps.py", "start_line": 10, "end_line": 12, "snippet": "def create_hcp(payload): return db.insert(payload)"}
    ]

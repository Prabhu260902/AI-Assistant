import chromadb
from chromadb.api.types import EmbeddingFunction

from services.hybrid_search import search_repo


class _FakeEmbeddingFunction(EmbeddingFunction):
    """Deterministic, no-network stand-in for Chroma's default embedding
    function — see tests/backend/test_ingest.py for the same pattern."""

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


def _seed_collection(monkeypatch):
    client = chromadb.EphemeralClient()
    collection = client.get_or_create_collection("hybrid-search-test-repo", embedding_function=_FakeEmbeddingFunction())
    collection.upsert(
        ids=["a", "b", "c"],
        documents=[
            "def create_hcp(payload): return db.insert(payload)",
            "def list_interactions(): return db.query(Interaction)",
            "import os\nimport sys",
        ],
        metadatas=[
            {"file_path": "backend/routers/hcps.py", "start_line": 10, "end_line": 12, "language": "python"},
            {"file_path": "backend/routers/interactions.py", "start_line": 5, "end_line": 7, "language": "python"},
            {"file_path": "backend/main.py", "start_line": 1, "end_line": 2, "language": "python"},
        ],
    )
    monkeypatch.setattr("services.hybrid_search.get_vector_store", lambda: _FakeVectorStore(client))
    return collection


def test_search_repo_finds_relevant_chunk_by_keyword(monkeypatch):
    _seed_collection(monkeypatch)

    results = search_repo("hybrid-search-test-repo", "create hcp", top_k=2)

    assert results
    assert results[0].file_path == "backend/routers/hcps.py"
    assert results[0].start_line == 10
    assert results[0].end_line == 12


def test_search_repo_returns_metadata_for_all_results(monkeypatch):
    _seed_collection(monkeypatch)

    results = search_repo("hybrid-search-test-repo", "interactions", top_k=3)

    assert all(r.file_path and r.language == "python" for r in results)


def test_search_repo_on_empty_collection_returns_empty_list(monkeypatch):
    client = chromadb.EphemeralClient()
    monkeypatch.setattr("services.hybrid_search.get_vector_store", lambda: _FakeVectorStore(client))

    results = search_repo("empty-repo", "anything", top_k=5)

    assert results == []

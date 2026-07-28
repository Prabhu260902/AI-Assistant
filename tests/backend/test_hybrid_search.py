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


def test_search_repo_returns_full_content_from_metadata_not_indexed_document(monkeypatch):
    """services/ingest.py embeds an import-stripped version of a mixed chunk
    to keep ranking clean, but stores the real, complete text in
    metadata["content"] for citations/LLM context — search_repo must read
    content from there, not from the (now import-stripped) indexed document."""
    client = chromadb.EphemeralClient()
    collection = client.get_or_create_collection(
        "hybrid-search-content-fallback-repo", embedding_function=_FakeEmbeddingFunction()
    )
    collection.upsert(
        ids=["a"],
        documents=["def handler(): return 'ok'"],  # import-stripped, as ingest.py would index it
        metadatas=[
            {
                "file_path": "app.py",
                "start_line": 1,
                "end_line": 3,
                "language": "python",
                "content": "import os\n\ndef handler(): return 'ok'",  # the real, full chunk
            }
        ],
    )
    monkeypatch.setattr("services.hybrid_search.get_vector_store", lambda: _FakeVectorStore(client))

    results = search_repo("hybrid-search-content-fallback-repo", "handler", top_k=1)

    assert results[0].content == "import os\n\ndef handler(): return 'ok'"


def test_search_repo_paginates_past_a_single_get_page(monkeypatch):
    """Regression test: a collection larger than one collection.get() page
    (33,218 chunks in a real repo) made Chroma's SQLite backend raise
    "too many SQL variables" on the old unbatched collection.get() call.
    Forces a tiny page size so a handful of documents already spans
    multiple pages, proving pagination collects every document rather than
    silently truncating to the first page."""
    monkeypatch.setattr("services.hybrid_search.GET_PAGE_SIZE", 2)

    client = chromadb.EphemeralClient()
    collection = client.get_or_create_collection(
        "hybrid-search-pagination-repo", embedding_function=_FakeEmbeddingFunction()
    )
    ids = [f"chunk-{i}" for i in range(5)]
    collection.upsert(
        ids=ids,
        documents=[f"def function_{i}(): return {i}" for i in range(5)],
        metadatas=[{"file_path": f"module_{i}.py", "start_line": 1, "end_line": 1, "language": "python"} for i in range(5)],
    )
    monkeypatch.setattr("services.hybrid_search.get_vector_store", lambda: _FakeVectorStore(client))

    results = search_repo("hybrid-search-pagination-repo", "function", top_k=5)

    assert {r.chunk_id for r in results} == set(ids)

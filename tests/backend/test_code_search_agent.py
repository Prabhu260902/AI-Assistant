import chromadb
from chromadb.api.types import EmbeddingFunction

from graphs.code_search import run_code_search


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


def _seed_collection(monkeypatch):
    client = chromadb.EphemeralClient()
    collection = client.get_or_create_collection("code-search-agent-test-repo", embedding_function=_FakeEmbeddingFunction())
    collection.upsert(
        ids=["a"],
        documents=["def create_hcp(payload): return db.insert(payload)"],
        metadatas=[{"file_path": "backend/routers/hcps.py", "start_line": 10, "end_line": 12, "language": "python"}],
    )
    monkeypatch.setattr("services.hybrid_search.get_vector_store", lambda: _FakeVectorStore(client))


def test_code_search_agent_returns_llm_answer_with_citations(monkeypatch):
    _seed_collection(monkeypatch)
    monkeypatch.setattr(
        "agents.code_search.get_llm_provider", lambda: _FakeLLMProvider("HCPs are created via create_hcp [1].")
    )

    state = run_code_search("code-search-agent-test-repo", "how do you create an hcp?", top_k=3)

    assert state["answer"] == "HCPs are created via create_hcp [1]."
    assert len(state["citations"]) == 1
    assert state["citations"][0]["file_path"] == "backend/routers/hcps.py"
    assert state["citations"][0]["start_line"] == 10
    assert state["citations"][0]["end_line"] == 12


def test_code_search_agent_skips_llm_call_when_no_results(monkeypatch):
    client = chromadb.EphemeralClient()
    monkeypatch.setattr("services.hybrid_search.get_vector_store", lambda: _FakeVectorStore(client))

    def _fail_if_called():
        raise AssertionError("LLM should not be called when there are no retrieval results")

    monkeypatch.setattr("agents.code_search.get_llm_provider", _fail_if_called)

    state = run_code_search("empty-repo", "anything", top_k=3)

    assert state["citations"] == []
    assert "No indexed code" in state["answer"]

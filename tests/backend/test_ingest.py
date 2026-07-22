import chromadb
from chromadb.api.types import EmbeddingFunction

from services.ingest import DENY_DIRS, _is_secret_file, _iter_source_files, _read_text, index_chunks, ingest_repository


def _write(path, content=""):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


class _FakeEmbeddingFunction(EmbeddingFunction):
    """Deterministic, no-network stand-in for Chroma's default (ONNX, downloaded on
    first use) embedding function, so these tests don't depend on network access."""

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


def _ephemeral_collection(client, name):
    return client.get_or_create_collection(name, embedding_function=_FakeEmbeddingFunction())


class _FakeVectorStore:
    def __init__(self, client):
        self._client = client

    def get_or_create_collection(self, name):
        return _ephemeral_collection(self._client, name)


def test_iter_source_files_skips_denylisted_dirs(tmp_path):
    _write(tmp_path / "app.py", "def a():\n    pass\n")
    _write(tmp_path / "node_modules" / "pkg" / "index.js", "console.log(1)")
    _write(tmp_path / "venv" / "lib" / "site.py", "x = 1")
    _write(tmp_path / ".git" / "HEAD", "ref: refs/heads/main")

    files = list(_iter_source_files(tmp_path))

    assert "app.py" in [f.name for f in files]
    touched_dirs = {part for f in files for part in f.relative_to(tmp_path).parts[:-1]}
    assert touched_dirs.isdisjoint(DENY_DIRS)


def test_read_text_returns_none_for_binary_file(tmp_path):
    path = tmp_path / "image.bin"
    path.write_bytes(bytes(range(256)))

    assert _read_text(path) is None


def test_secret_files_are_never_ingested(tmp_path, monkeypatch):
    _write(tmp_path / "main.py", "def handler():\n    return 'ok'\n")
    _write(tmp_path / ".env", "GROQ_API_KEY=super-secret-value\n")
    _write(tmp_path / "backend" / ".env.local", "DATABASE_URL=postgres://secret\n")
    _write(tmp_path / "id_rsa", "-----BEGIN OPENSSH PRIVATE KEY-----\nsecret\n")

    assert _is_secret_file(".env")
    assert _is_secret_file(".env.local")
    assert _is_secret_file("id_rsa")
    assert not _is_secret_file("main.py")

    client = chromadb.EphemeralClient()
    monkeypatch.setattr("services.ingest.get_vector_store", lambda: _FakeVectorStore(client))

    ingest_repository(str(tmp_path), repo_id="secret-fixture-repo")

    collection = _ephemeral_collection(client, "secret-fixture-repo")
    all_docs = collection.get()
    combined = " ".join(all_docs["documents"])
    assert "super-secret-value" not in combined
    assert "postgres://secret" not in combined
    assert "BEGIN OPENSSH PRIVATE KEY" not in combined


def test_index_chunks_upserts_into_ephemeral_chroma():
    client = chromadb.EphemeralClient()
    collection = _ephemeral_collection(client, "test-repo")
    chunks = [
        {"id": "a", "document": "def foo(): pass", "metadata": {"file_path": "a.py"}},
        {"id": "b", "document": "def bar(): pass", "metadata": {"file_path": "b.py"}},
    ]

    count = index_chunks(collection, chunks)

    assert count == 2
    assert collection.count() == 2


def test_index_chunks_upsert_is_idempotent():
    client = chromadb.EphemeralClient()
    collection = _ephemeral_collection(client, "test-repo-2")
    chunks = [{"id": "a", "document": "def foo(): pass", "metadata": {"file_path": "a.py"}}]

    index_chunks(collection, chunks)
    index_chunks(collection, chunks)

    assert collection.count() == 1


def test_ingest_repository_end_to_end_against_local_fixture(tmp_path, monkeypatch):
    _write(tmp_path / "main.py", "def handler():\n    return 'ok'\n")
    _write(tmp_path / "node_modules" / "pkg" / "index.js", "console.log(1)")
    _write(tmp_path / "notes.md", "# Title\n\nSome notes here.\n")

    client = chromadb.EphemeralClient()
    monkeypatch.setattr("services.ingest.get_vector_store", lambda: _FakeVectorStore(client))

    summary = ingest_repository(str(tmp_path), repo_id="fixture-repo")

    assert summary.files_indexed >= 2
    assert summary.chunks_indexed > 0
    assert _ephemeral_collection(client, "fixture-repo").count() == summary.chunks_indexed

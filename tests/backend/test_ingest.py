import chromadb
from chromadb.api.types import EmbeddingFunction

from services.ingest import (
    DENY_DIRS,
    _is_import_dominated,
    _is_secret_file,
    _iter_source_files,
    _read_text,
    _strip_import_lines,
    index_chunks,
    ingest_repository,
)


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
    collection = _ephemeral_collection(client, "ingest-test-repo-1")
    chunks = [
        {"id": "a", "document": "def foo(): pass", "metadata": {"file_path": "a.py"}},
        {"id": "b", "document": "def bar(): pass", "metadata": {"file_path": "b.py"}},
    ]

    count = index_chunks(collection, chunks)

    assert count == 2
    assert collection.count() == 2


def test_index_chunks_upsert_is_idempotent():
    client = chromadb.EphemeralClient()
    collection = _ephemeral_collection(client, "ingest-test-repo-2")
    chunks = [{"id": "a", "document": "def foo(): pass", "metadata": {"file_path": "a.py"}}]

    index_chunks(collection, chunks)
    index_chunks(collection, chunks)

    assert collection.count() == 1


def test_is_import_dominated_true_for_pure_import_block():
    content = "\n".join(
        [
            "import 'dart:convert';",
            "import 'package:flutter/material.dart';",
            "import '../../config/api_client.dart';",
            "#include \"Warnings.xcconfig\"",
        ]
    )
    assert _is_import_dominated(content)


def test_is_import_dominated_false_when_real_code_follows_imports():
    """Regression test: a real file's leading chunk had 11 import lines
    followed by a real class declaration (8 more lines) — 58% import lines,
    below the threshold. Confirms the filter doesn't discard chunks that
    happen to start with imports but carry real, useful content too."""
    content = "\n".join(
        [
            "import 'dart:convert';",
            "import 'package:flutter/material.dart';",
            "",
            "class ManageProductsScreen extends StatefulWidget {",
            "  const ManageProductsScreen({Key? key}) : super(key: key);",
            "",
            "  @override",
            "  State<ManageProductsScreen> createState() => _ManageProductsScreenState();",
            "}",
        ]
    )
    assert not _is_import_dominated(content)


def test_is_import_dominated_false_for_empty_content():
    assert not _is_import_dominated("")
    assert not _is_import_dominated("   \n\n  ")


def test_strip_import_lines_removes_only_import_lines():
    """Regression test: this exact 20-line chunk (11 import lines + a real
    class stub) kept outranking chunks that actually answered the user's
    question, because import vocabulary repeats across nearly every file in
    the corpus. Stripping the import lines before embedding removes that
    noise from what drives ranking."""
    content = "\n".join(
        [
            "import 'dart:convert';",
            "import 'package:flutter/material.dart';",
            "",
            "class ManageProductsScreen extends StatefulWidget {",
            "  const ManageProductsScreen({Key? key}) : super(key: key);",
            "}",
        ]
    )

    stripped = _strip_import_lines(content)

    assert "import" not in stripped
    assert "class ManageProductsScreen" in stripped


def test_strip_import_lines_falls_back_to_original_when_nothing_survives():
    content = "import 'dart:convert';\nimport 'package:flutter/material.dart';"

    assert _strip_import_lines(content) == content


def test_ingest_repository_strips_imports_from_indexed_text_but_keeps_full_content(tmp_path, monkeypatch):
    _write(tmp_path / "mixed.py", "import os\nimport sys\n\n\ndef handler():\n    return 'ok'\n")

    client = chromadb.EphemeralClient()
    monkeypatch.setattr("services.ingest.get_vector_store", lambda: _FakeVectorStore(client))

    ingest_repository(str(tmp_path), repo_id="strip-fixture-repo")

    collection = _ephemeral_collection(client, "strip-fixture-repo")
    all_docs = collection.get()
    assert len(all_docs["ids"]) == 1

    indexed_document = all_docs["documents"][0]
    stored_content = all_docs["metadatas"][0]["content"]

    # what gets embedded/BM25-indexed has the import lines removed...
    assert "import os" not in indexed_document
    assert "def handler" in indexed_document

    # ...but the original, complete text is preserved for citations/LLM context
    assert "import os" in stored_content
    assert "def handler" in stored_content


def test_ingest_repository_skips_import_only_files(tmp_path, monkeypatch):
    _write(
        tmp_path / "barrel.py",
        "\n".join(f"from .module_{i} import Thing{i}" for i in range(20)) + "\n",
    )
    _write(tmp_path / "real.py", "def handler():\n    return 'ok'\n")

    client = chromadb.EphemeralClient()
    monkeypatch.setattr("services.ingest.get_vector_store", lambda: _FakeVectorStore(client))

    summary = ingest_repository(str(tmp_path), repo_id="import-only-fixture-repo")

    collection = _ephemeral_collection(client, "import-only-fixture-repo")
    all_docs = collection.get()
    combined = " ".join(all_docs["documents"])
    assert "Thing0" not in combined
    assert "handler" in combined
    assert summary.files_skipped >= 1


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

"""Repository ingestion: walk a repo, chunk files, index chunks into the vector store."""

import os
from dataclasses import dataclass
from pathlib import Path

from services.chunker import chunk_text
from services.repo_loader import derive_repo_id, resolve_repo
from services.vectorstore import get_vector_store

DENY_DIRS = {
    ".git",
    ".venv",
    "venv",
    "env",
    "node_modules",
    "dist",
    "build",
    ".next",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".idea",
    ".vscode",
    ".cache",
    ".tox",
}
MAX_FILE_SIZE_BYTES = 1_000_000
BATCH_SIZE = 100

# Never read/embed files that commonly hold secrets, regardless of directory.
DENY_FILENAME_PREFIXES = (".env",)
DENY_FILENAMES = {
    "id_rsa",
    "id_ed25519",
    "id_ecdsa",
    "id_dsa",
    ".npmrc",
    ".pypirc",
    ".netrc",
    "credentials.json",
}
DENY_FILE_SUFFIXES = (".pem", ".key", ".p12", ".pfx", ".crt", ".cer")


def _is_secret_file(filename: str) -> bool:
    if filename in DENY_FILENAMES:
        return True
    if filename.startswith(DENY_FILENAME_PREFIXES):
        return True
    if filename.endswith(DENY_FILE_SUFFIXES):
        return True
    return False


@dataclass
class IngestSummary:
    repo_id: str
    files_scanned: int = 0
    files_indexed: int = 0
    files_skipped: int = 0
    chunks_indexed: int = 0


def _iter_source_files(repo_path: Path):
    for root, dirs, files in os.walk(repo_path):
        dirs[:] = [d for d in dirs if d not in DENY_DIRS and not d.endswith(".egg-info")]
        for filename in files:
            yield Path(root) / filename


def _read_text(path: Path) -> str | None:
    try:
        if path.stat().st_size > MAX_FILE_SIZE_BYTES:
            return None
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def index_chunks(collection, chunks: list[dict]) -> int:
    """chunks: list of {id, document, metadata} dicts. Upserts in batches (idempotent)."""
    indexed = 0
    for i in range(0, len(chunks), BATCH_SIZE):
        batch = chunks[i : i + BATCH_SIZE]
        collection.upsert(
            ids=[c["id"] for c in batch],
            documents=[c["document"] for c in batch],
            metadatas=[c["metadata"] for c in batch],
        )
        indexed += len(batch)
    return indexed


def ingest_repository(source: str, repo_id: str | None = None) -> IngestSummary:
    repo_path = resolve_repo(source)
    repo_id = repo_id or derive_repo_id(source)
    summary = IngestSummary(repo_id=repo_id)

    pending: list[dict] = []
    for file_path in _iter_source_files(repo_path):
        summary.files_scanned += 1
        if _is_secret_file(file_path.name):
            summary.files_skipped += 1
            continue

        text = _read_text(file_path)
        if text is None:
            summary.files_skipped += 1
            continue

        rel_path = str(file_path.relative_to(repo_path))
        chunks = chunk_text(text, rel_path)
        if not chunks:
            summary.files_skipped += 1
            continue

        summary.files_indexed += 1
        for chunk in chunks:
            chunk_id = f"{repo_id}:{rel_path}:{chunk.start_byte}-{chunk.end_byte}"
            pending.append(
                {
                    "id": chunk_id,
                    "document": chunk.content,
                    "metadata": {
                        "repo_id": repo_id,
                        "file_path": rel_path,
                        "start_line": chunk.start_line,
                        "end_line": chunk.end_line,
                        "language": chunk.language,
                    },
                }
            )

    collection = get_vector_store().get_or_create_collection(repo_id)
    summary.chunks_indexed = index_chunks(collection, pending)
    return summary

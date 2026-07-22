"""Vector store interface.

Callers depend only on `VectorStore` / `get_vector_store()`. Migrating from
Chroma to Qdrant later is a config change via `VECTOR_STORE_PROVIDER` plus a
new adapter class here, not a rewrite of calling code. Collection
population/embedding logic arrives in Phase 2 — this phase only wires the
connection.
"""

from typing import Any, Protocol

import chromadb

from services.config import get_settings


class VectorStore(Protocol):
    def get_or_create_collection(self, name: str) -> Any:
        """Return a handle to a named collection, creating it if needed."""
        ...


class ChromaVectorStore:
    def __init__(self, host: str, port: int) -> None:
        self._client = chromadb.HttpClient(host=host, port=port)

    def get_or_create_collection(self, name: str) -> Any:
        return self._client.get_or_create_collection(name)


def get_vector_store() -> VectorStore:
    settings = get_settings()
    if settings.vector_store_provider == "chroma":
        return ChromaVectorStore(host=settings.chroma_host, port=settings.chroma_port)
    raise ValueError(f"Unsupported vector store provider: {settings.vector_store_provider}")

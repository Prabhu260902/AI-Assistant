"""Hybrid (vector + keyword) search over a repo's indexed chunks.

Combines Chroma's vector-similarity ranking with hand-rolled BM25 keyword
ranking (`services.keyword_search`) via Reciprocal Rank Fusion — fusing by
rank position avoids having to normalize two incomparable score scales
(cosine distance vs. BM25 score) onto one another.
"""

from dataclasses import dataclass

from services.keyword_search import BM25Index
from services.vectorstore import get_vector_store

VECTOR_CANDIDATES = 15
KEYWORD_CANDIDATES = 15
RRF_K = 60


@dataclass
class SearchResult:
    chunk_id: str
    content: str
    file_path: str
    start_line: int
    end_line: int
    language: str
    score: float


def _reciprocal_rank_fusion(rankings: list[list[str]], k: int = RRF_K) -> dict[str, float]:
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, doc_id in enumerate(ranking, start=1):
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank)
    return scores


def search_repo(repo_id: str, query: str, top_k: int = 5) -> list[SearchResult]:
    collection = get_vector_store().get_or_create_collection(repo_id)

    all_chunks = collection.get()
    all_ids: list[str] = all_chunks.get("ids") or []
    if not all_ids:
        return []

    all_documents: list[str] = all_chunks.get("documents") or []
    documents_by_id = dict(zip(all_ids, all_documents))
    metadatas_by_id = dict(zip(all_ids, all_chunks.get("metadatas") or []))

    vector_result = collection.query(query_texts=[query], n_results=min(VECTOR_CANDIDATES, len(all_ids)))
    vector_ids = (vector_result.get("ids") or [[]])[0]

    bm25 = BM25Index(list(zip(all_ids, all_documents)))
    keyword_ids = [doc_id for doc_id, _ in bm25.search(query, top_k=min(KEYWORD_CANDIDATES, len(all_ids)))]

    fused = _reciprocal_rank_fusion([vector_ids, keyword_ids])
    ranked_ids = sorted(fused, key=lambda doc_id: fused[doc_id], reverse=True)

    results = []
    for chunk_id in ranked_ids[:top_k]:
        metadata = metadatas_by_id.get(chunk_id) or {}
        results.append(
            SearchResult(
                chunk_id=chunk_id,
                content=documents_by_id.get(chunk_id, ""),
                file_path=metadata.get("file_path", ""),
                start_line=metadata.get("start_line", 0),
                end_line=metadata.get("end_line", 0),
                language=metadata.get("language", ""),
                score=fused[chunk_id],
            )
        )
    return results

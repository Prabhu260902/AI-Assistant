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

# collection.get() with no limit asks Chroma's SQLite backend to bind one
# variable per row (or more) in a single query — fine for a few hundred
# chunks, but a large repo can have tens of thousands, which blows past
# SQLite's bound-variable ceiling entirely (hit for real on a 33k-chunk
# collection: "too many SQL variables"). Paginating keeps every individual
# call's row count small regardless of collection size.
GET_PAGE_SIZE = 1000


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


def _get_all_chunks(collection) -> tuple[list[str], list[str], list[dict]]:
    all_ids: list[str] = []
    all_documents: list[str] = []
    all_metadatas: list[dict] = []
    offset = 0
    while True:
        page = collection.get(limit=GET_PAGE_SIZE, offset=offset)
        page_ids: list[str] = page.get("ids") or []
        if not page_ids:
            break
        all_ids.extend(page_ids)
        all_documents.extend(page.get("documents") or [])
        all_metadatas.extend(page.get("metadatas") or [])
        if len(page_ids) < GET_PAGE_SIZE:
            break
        offset += GET_PAGE_SIZE
    return all_ids, all_documents, all_metadatas


def search_repo(repo_id: str, query: str, top_k: int = 25) -> list[SearchResult]:
    collection = get_vector_store().get_or_create_collection(repo_id)

    all_ids, all_documents, all_metadatas = _get_all_chunks(collection)
    if not all_ids:
        return []

    documents_by_id = dict(zip(all_ids, all_documents))
    metadatas_by_id = dict(zip(all_ids, all_metadatas))

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
                # metadata["content"] is the real, complete chunk text;
                # the indexed `document` has import lines stripped out to
                # keep them from diluting ranking (services/ingest.py) — the
                # `.get(..., documents_by_id...)` fallback only matters for
                # data indexed before that split existed.
                content=metadata.get("content") or documents_by_id.get(chunk_id, ""),
                file_path=metadata.get("file_path", ""),
                start_line=metadata.get("start_line", 0),
                end_line=metadata.get("end_line", 0),
                language=metadata.get("language", ""),
                score=fused[chunk_id],
            )
        )
    return results

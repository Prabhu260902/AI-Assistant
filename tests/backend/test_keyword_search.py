from services.keyword_search import BM25Index, tokenize


def test_tokenize_splits_snake_case_and_camel_case():
    assert tokenize("create_hcp") == ["create", "hcp"]
    assert tokenize("createHcp") == ["create", "hcp"]
    assert tokenize("HTTPServerError") == ["http", "server", "error"]


def test_bm25_ranks_matching_document_above_unrelated_ones():
    index = BM25Index(
        [
            ("a", "def create_hcp(payload): return db.insert(payload)"),
            ("b", "def list_interactions(): return db.query(Interaction)"),
            ("c", "import os\nimport sys"),
        ]
    )

    results = index.search("create hcp", top_k=3)

    assert results[0][0] == "a"
    assert all(doc_id != "c" for doc_id, _ in results)


def test_bm25_search_on_empty_index_returns_empty():
    assert BM25Index([]).search("anything", top_k=5) == []


def test_bm25_search_with_no_matching_terms_returns_empty():
    index = BM25Index([("a", "def helper(): pass")])

    assert index.search("completely unrelated banana", top_k=3) == []

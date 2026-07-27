"""Shared state for the Code Search Agent's graph."""

from typing import TypedDict

from services.hybrid_search import SearchResult


class Citation(TypedDict):
    file_path: str
    start_line: int
    end_line: int
    snippet: str


class CodeSearchState(TypedDict):
    repo_id: str
    query: str
    top_k: int
    results: list[SearchResult]
    answer: str
    citations: list[Citation]

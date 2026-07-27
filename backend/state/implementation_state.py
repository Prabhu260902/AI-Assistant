"""Shared state for the Implementation Assistant's graph."""

from typing import TypedDict

from pydantic import BaseModel

from services.hybrid_search import SearchResult


class ProposedChange(BaseModel):
    file_path: str
    diff: str
    new_content: str


class ImplementationState(TypedDict):
    repo_id: str
    feature_description: str
    top_k: int
    plan: str
    risks: list[str]
    context_results: list[SearchResult]
    proposed_changes: list[ProposedChange]

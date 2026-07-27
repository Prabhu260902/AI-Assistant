"""Shared state for the Feature Planner Agent's graph."""

from typing import TypedDict

from services.hybrid_search import SearchResult
from services.impact_analysis import AffectedModule


class FeaturePlanState(TypedDict):
    repo_id: str
    feature_description: str
    top_k: int
    context_results: list[SearchResult]
    affected_modules: list[AffectedModule]
    plan: str
    risks: list[str]

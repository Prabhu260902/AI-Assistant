"""Shared state for the PR Review Agent's graph."""

from typing import Literal, TypedDict

from pydantic import BaseModel


class Finding(BaseModel):
    category: Literal["correctness", "security", "performance", "test_coverage"]
    severity: Literal["low", "medium", "high"]
    file_path: str
    line: int | None = None
    description: str


class ReviewBreakdown(BaseModel):
    summary: str
    findings: list[Finding]


class ReviewState(TypedDict):
    repo_id: str
    base_ref: str
    head_ref: str
    diff_text: str
    findings: list[Finding]
    summary: str

"""Shared state for the Ticket Generator Agent's graph.

Epic/Story/Task are Pydantic models (not dataclasses, unlike most other
per-item types in this codebase) because this phase's output is validated
directly from the LLM's JSON response via `TicketBreakdown.model_validate_json`,
and the same models double as the FastAPI response shape with no
dataclass-to-dict conversion step.
"""

from typing import TypedDict

from pydantic import BaseModel

from services.impact_analysis import AffectedModule


class Task(BaseModel):
    title: str
    description: str


class Story(BaseModel):
    title: str
    description: str
    acceptance_criteria: list[str]
    test_cases: list[str]
    tasks: list[Task]


class Epic(BaseModel):
    title: str
    description: str
    stories: list[Story]


class TicketBreakdown(BaseModel):
    epics: list[Epic]


class TicketGenState(TypedDict):
    repo_id: str
    feature_description: str
    top_k: int
    plan: str
    affected_modules: list[AffectedModule]
    risks: list[str]
    epics: list[Epic]

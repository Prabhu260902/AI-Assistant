from typing import Literal, TypedDict

from pydantic import BaseModel

Intent = Literal["search", "architecture", "plan", "tickets", "implement", "review"]


class RouterClassification(BaseModel):
    intent: Intent
    base_ref: str | None = None
    head_ref: str | None = None


class RouterState(TypedDict):
    repo_id: str
    message: str
    top_k: int
    intent: str
    base_ref: str | None
    head_ref: str | None
    result: dict

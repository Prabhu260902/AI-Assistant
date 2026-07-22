"""Shared LangGraph state schemas."""

from typing import TypedDict


class PassthroughState(TypedDict):
    input: str
    output: str

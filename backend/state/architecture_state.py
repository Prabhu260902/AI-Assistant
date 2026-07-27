"""Shared state for the Architecture Assistant's graph."""

from typing import TypedDict

from services.architecture_graph import FlowGraph


class ArchitectureState(TypedDict):
    repo_id: str
    query: str
    top_k: int
    flow_graph: FlowGraph | None
    mermaid_diagram: str
    explanation: str

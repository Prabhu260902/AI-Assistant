"""Implementation Assistant graph: plan (Phase 5, reused) -> generate_code.

Read-only end to end — writing to disk only happens via the separate
`services.code_apply.apply_changes`, called explicitly by the caller after
reviewing the diffs this graph produces.
"""

from langgraph.graph import END, START, StateGraph

from agents.implementation import generate_code_node, plan_node
from state.implementation_state import ImplementationState


def build_implementation_graph():
    graph = StateGraph(ImplementationState)
    graph.add_node("plan", plan_node)
    graph.add_node("generate_code", generate_code_node)
    graph.add_edge(START, "plan")
    graph.add_edge("plan", "generate_code")
    graph.add_edge("generate_code", END)
    return graph.compile()


_compiled_graph = build_implementation_graph()


def run_implementation(repo_id: str, feature_description: str, top_k: int = 5) -> ImplementationState:
    return _compiled_graph.invoke(
        {
            "repo_id": repo_id,
            "feature_description": feature_description,
            "top_k": top_k,
            "plan": "",
            "risks": [],
            "context_results": [],
            "proposed_changes": [],
        }
    )

"""PR Review Agent graph: diff -> generate_review."""

from langgraph.graph import END, START, StateGraph

from agents.pr_review import diff_node, generate_review_node
from state.review_state import ReviewState


def build_pr_review_graph():
    graph = StateGraph(ReviewState)
    graph.add_node("diff", diff_node)
    graph.add_node("generate_review", generate_review_node)
    graph.add_edge(START, "diff")
    graph.add_edge("diff", "generate_review")
    graph.add_edge("generate_review", END)
    return graph.compile()


_compiled_graph = build_pr_review_graph()


def run_pr_review(repo_id: str, base_ref: str, head_ref: str) -> ReviewState:
    return _compiled_graph.invoke(
        {
            "repo_id": repo_id,
            "base_ref": base_ref,
            "head_ref": head_ref,
            "diff_text": "",
            "findings": [],
            "summary": "",
        }
    )

"""Architecture Assistant graph: build_graph (grounded, no LLM) -> explain (LLM narration)."""

from langgraph.graph import END, START, StateGraph

from agents.architecture import build_graph_node, explain_node
from state.architecture_state import ArchitectureState


def build_architecture_graph():
    graph = StateGraph(ArchitectureState)
    graph.add_node("build_graph", build_graph_node)
    graph.add_node("explain", explain_node)
    graph.add_edge(START, "build_graph")
    graph.add_edge("build_graph", "explain")
    graph.add_edge("explain", END)
    return graph.compile()


_compiled_graph = build_architecture_graph()


def run_architecture_explanation(repo_id: str, query: str, top_k: int = 5) -> ArchitectureState:
    return _compiled_graph.invoke(
        {
            "repo_id": repo_id,
            "query": query,
            "top_k": top_k,
            "flow_graph": None,
            "mermaid_diagram": "",
            "explanation": "",
        }
    )

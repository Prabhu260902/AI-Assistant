"""Engineering Copilot graph: classify -> dispatch."""

from langgraph.graph import END, START, StateGraph

from agents.router import classify_node, dispatch_node
from state.router_state import RouterState


def build_router_graph():
    graph = StateGraph(RouterState)
    graph.add_node("classify", classify_node)
    graph.add_node("dispatch", dispatch_node)
    graph.add_edge(START, "classify")
    graph.add_edge("classify", "dispatch")
    graph.add_edge("dispatch", END)
    return graph.compile()


_compiled_graph = build_router_graph()


def run_copilot(repo_id: str, message: str, top_k: int = 25) -> RouterState:
    return _compiled_graph.invoke(
        {
            "repo_id": repo_id,
            "message": message,
            "top_k": top_k,
            "intent": "",
            "base_ref": None,
            "head_ref": None,
            "result": {},
        }
    )

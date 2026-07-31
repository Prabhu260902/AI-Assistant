"""Code Search Agent graph: retrieve (hybrid search) -> generate (LLM summary + citations)."""

from langgraph.graph import END, START, StateGraph

from agents.code_search import generate_node, retrieve_node
from state.code_search_state import CodeSearchState


def build_code_search_graph():
    graph = StateGraph(CodeSearchState)
    graph.add_node("retrieve", retrieve_node)
    graph.add_node("generate", generate_node)
    graph.add_edge(START, "retrieve")
    graph.add_edge("retrieve", "generate")
    graph.add_edge("generate", END)
    return graph.compile()


_compiled_graph = build_code_search_graph()


def run_code_search(repo_id: str, query: str, top_k: int = 25) -> CodeSearchState:
    return _compiled_graph.invoke(
        {"repo_id": repo_id, "query": query, "top_k": top_k, "results": [], "answer": "", "citations": []}
    )

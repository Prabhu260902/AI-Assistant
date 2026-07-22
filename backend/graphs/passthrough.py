"""Minimal end-to-end LangGraph graph: a single passthrough node.

Proves the graph runtime wiring (state, node, compile, invoke) works before
later phases add real agent nodes.
"""

from langgraph.graph import END, START, StateGraph

from state.graph_state import PassthroughState


def passthrough_node(state: PassthroughState) -> PassthroughState:
    return {"input": state["input"], "output": state["input"]}


def build_passthrough_graph():
    graph = StateGraph(PassthroughState)
    graph.add_node("passthrough", passthrough_node)
    graph.add_edge(START, "passthrough")
    graph.add_edge("passthrough", END)
    return graph.compile()


_compiled_graph = build_passthrough_graph()


def run_passthrough(input_text: str) -> str:
    result = _compiled_graph.invoke({"input": input_text, "output": ""})
    return result["output"]

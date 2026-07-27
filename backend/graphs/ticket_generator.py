"""Ticket Generator Agent graph: plan (Phase 5, reused) -> generate_tickets."""

from langgraph.graph import END, START, StateGraph

from agents.ticket_generator import generate_tickets_node, plan_node
from state.ticket_state import TicketGenState


def build_ticket_generator_graph():
    graph = StateGraph(TicketGenState)
    graph.add_node("plan", plan_node)
    graph.add_node("generate_tickets", generate_tickets_node)
    graph.add_edge(START, "plan")
    graph.add_edge("plan", "generate_tickets")
    graph.add_edge("generate_tickets", END)
    return graph.compile()


_compiled_graph = build_ticket_generator_graph()


def run_generate_tickets(repo_id: str, feature_description: str, top_k: int = 5) -> TicketGenState:
    return _compiled_graph.invoke(
        {
            "repo_id": repo_id,
            "feature_description": feature_description,
            "top_k": top_k,
            "plan": "",
            "affected_modules": [],
            "risks": [],
            "epics": [],
        }
    )

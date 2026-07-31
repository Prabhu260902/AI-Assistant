"""Feature Planner Agent graph: retrieve -> analyze_impact -> generate."""

from langgraph.graph import END, START, StateGraph

from agents.feature_planner import analyze_impact_node, generate_node, retrieve_node
from state.feature_planner_state import FeaturePlanState


def build_feature_planner_graph():
    graph = StateGraph(FeaturePlanState)
    graph.add_node("retrieve", retrieve_node)
    graph.add_node("analyze_impact", analyze_impact_node)
    graph.add_node("generate", generate_node)
    graph.add_edge(START, "retrieve")
    graph.add_edge("retrieve", "analyze_impact")
    graph.add_edge("analyze_impact", "generate")
    graph.add_edge("generate", END)
    return graph.compile()


_compiled_graph = build_feature_planner_graph()


def run_feature_plan(repo_id: str, feature_description: str, top_k: int = 25) -> FeaturePlanState:
    return _compiled_graph.invoke(
        {
            "repo_id": repo_id,
            "feature_description": feature_description,
            "top_k": top_k,
            "context_results": [],
            "affected_modules": [],
            "plan": "",
            "risks": [],
        }
    )

"""Architecture Assistant: locate a starting point via hybrid search, build
a grounded call-graph flow from it, render Mermaid, then have the LLM
narrate the already-built graph in prose — it never invents the structure.
"""

from prompts.architecture import build_architecture_prompt
from services.architecture_graph import build_flow_graph, find_starting_point
from services.hybrid_search import search_repo
from services.llm import get_llm_provider
from services.mermaid import render_flow_graph
from state.architecture_state import ArchitectureState


def build_graph_node(state: ArchitectureState) -> dict:
    results = search_repo(state["repo_id"], state["query"], top_k=state.get("top_k", 25))

    # Not every hit resolves to a traceable symbol (e.g. README.md has no
    # Postgres File/Symbol rows at all) — try each hit in ranked order
    # rather than giving up after the very first one fails.
    start = None
    for hit in results:
        start = find_starting_point(state["repo_id"], hit.file_path, hit.start_line, hit.end_line)
        if start is not None:
            break

    if start is None:
        return {"flow_graph": None, "mermaid_diagram": ""}

    symbol_id, start_node = start
    flow_graph = build_flow_graph(state["repo_id"], symbol_id, start_node)
    return {"flow_graph": flow_graph, "mermaid_diagram": render_flow_graph(flow_graph)}


def explain_node(state: ArchitectureState) -> dict:
    flow_graph = state["flow_graph"]
    if flow_graph is None or not flow_graph.nodes:
        return {"explanation": "Could not find a relevant starting point in the codebase for this question."}

    prompt = build_architecture_prompt(state["query"], flow_graph)
    explanation = get_llm_provider().complete(prompt)
    return {"explanation": explanation}

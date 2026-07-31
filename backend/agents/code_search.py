"""Code Search Agent: retrieve relevant chunks, then summarize with citations."""

from prompts.code_search import build_search_prompt
from services.hybrid_search import search_repo
from services.llm import get_llm_provider
from state.code_search_state import CodeSearchState


def retrieve_node(state: CodeSearchState) -> dict:
    results = search_repo(state["repo_id"], state["query"], top_k=state.get("top_k", 25))
    return {"results": results}


def generate_node(state: CodeSearchState) -> dict:
    results = state["results"]
    if not results:
        return {
            "answer": "No indexed code was found for this repository, or nothing matched the query.",
            "citations": [],
        }

    prompt = build_search_prompt(state["query"], results)
    answer = get_llm_provider().complete(prompt)

    citations = [
        {
            "file_path": result.file_path,
            "start_line": result.start_line,
            "end_line": result.end_line,
            "snippet": result.content[:200],
        }
        for result in results
    ]
    return {"answer": answer, "citations": citations}

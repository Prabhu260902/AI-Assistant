"""Prompt template for the Code Search Agent."""

from services.hybrid_search import SearchResult

_SYSTEM_INSTRUCTIONS = (
    "You are a code search assistant. Answer the question using ONLY the "
    "numbered code excerpts below — do not use outside knowledge. Cite the "
    "excerpts you rely on using their bracket number, e.g. [1]. If the "
    "excerpts don't contain enough information to answer, say so plainly."
)


def build_search_prompt(query: str, results: list[SearchResult]) -> str:
    blocks = []
    for i, result in enumerate(results, start=1):
        label = f"[{i}] {result.file_path}:{result.start_line}-{result.end_line}"
        blocks.append(f"{label}\n{result.content}")

    context = "\n\n".join(blocks)
    return f"{_SYSTEM_INSTRUCTIONS}\n\nQuestion: {query}\n\nCode excerpts:\n\n{context}\n\nAnswer:"

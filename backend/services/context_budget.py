"""Shared budget for assembling multiple retrieved chunks into one LLM
prompt, so a higher top_k can't grow a request past what Groq's API will
accept.

Confirmed real: raising top_k from 5 to 25 made a real query's assembled
prompt reach 34,626 characters, and Groq's API rejected it outright with
"HTTP Error 413: Payload Too Large" — a request-size gate enforced ahead of
the model, not the model's own (much larger) context window. Nothing in
this codebase capped how much retrieved content gets joined into a single
prompt; top_k only ever controlled how many candidates retrieval considers.
Truncating what gets joined keeps those two concerns independent — a higher
top_k can still mean "rank over more candidates" without meaning "cram all
of them into one request."
"""

MAX_CONTEXT_CHARS = 8000


def truncate_blocks_to_budget(blocks: list[str], max_chars: int = MAX_CONTEXT_CHARS) -> list[str]:
    """Keeps blocks in their given (already-ranked) order, dropping any
    trailing blocks once the running total would exceed max_chars. Always
    keeps at least the first block even if it alone exceeds the budget —
    an empty prompt is worse than one slightly over budget."""
    kept: list[str] = []
    total = 0
    for block in blocks:
        if kept and total + len(block) > max_chars:
            break
        kept.append(block)
        total += len(block)
    return kept

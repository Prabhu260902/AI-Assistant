from prompts.code_search import build_search_prompt
from prompts.feature_planner import build_planner_prompt
from services.context_budget import MAX_CONTEXT_CHARS, truncate_blocks_to_budget
from services.hybrid_search import SearchResult


def test_truncate_blocks_to_budget_keeps_everything_under_budget():
    blocks = ["a" * 100, "b" * 100, "c" * 100]

    assert truncate_blocks_to_budget(blocks, max_chars=1000) == blocks


def test_truncate_blocks_to_budget_drops_trailing_blocks_over_budget():
    blocks = ["a" * 100, "b" * 100, "c" * 100]

    kept = truncate_blocks_to_budget(blocks, max_chars=150)

    assert kept == ["a" * 100]


def test_truncate_blocks_to_budget_always_keeps_first_block_even_if_oversized():
    blocks = ["a" * 500, "b" * 10]

    kept = truncate_blocks_to_budget(blocks, max_chars=10)

    assert kept == ["a" * 500]


def test_truncate_blocks_to_budget_handles_empty_input():
    assert truncate_blocks_to_budget([], max_chars=1000) == []


def _make_result(i: int, content_size: int) -> SearchResult:
    return SearchResult(
        chunk_id=f"chunk-{i}",
        content="x" * content_size,
        file_path=f"file_{i}.py",
        start_line=1,
        end_line=10,
        language="python",
        score=1.0,
    )


def test_build_search_prompt_stays_within_budget_regardless_of_result_count():
    """Regression test: raising top_k from 5 to 25 made a real query's
    assembled prompt reach 34,626 characters, and Groq's API rejected it
    outright with "413 Payload Too Large" — a request-size gate hit well
    before the model's own context window. 25 large results must not blow
    the prompt past the shared budget."""
    results = [_make_result(i, content_size=2000) for i in range(25)]

    prompt = build_search_prompt("some question", results)

    # generous slack for the fixed system instructions/question/labels
    # around the truncated excerpt blocks themselves
    assert len(prompt) < MAX_CONTEXT_CHARS + 2000


def test_build_planner_prompt_stays_within_budget_regardless_of_result_count():
    results = [_make_result(i, content_size=2000) for i in range(25)]

    prompt = build_planner_prompt("some feature", results, [])

    assert len(prompt) < MAX_CONTEXT_CHARS + 2000

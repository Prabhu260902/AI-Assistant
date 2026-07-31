"""Implementation Assistant: run the Phase 5 planner, then regenerate each
directly-relevant file's full content and compute a diff for human review.

Never writes to disk — that only happens in services.code_apply, behind a
separate explicit apply step the caller must invoke after reviewing diffs.
"""

import difflib
from pathlib import Path

from graphs.feature_planner import run_feature_plan
from prompts.implementation import build_implementation_prompt
from services.llm import get_llm_provider
from services.repo_registry import get_repo_source
from state.implementation_state import ImplementationState, ProposedChange


def _strip_wrapping_code_fence(text: str) -> str:
    """Strip a single ``` fence pair only if it wraps the ENTIRE response
    (first and last line). Must not touch ``` sequences that are part of the
    file's own real content (e.g. a README with embedded code blocks) —
    a line-by-line regex here previously corrupted every fenced example in
    non-code files it regenerated."""
    stripped = text.strip()
    lines = stripped.splitlines()
    if len(lines) >= 2 and lines[0].startswith("```") and lines[-1].strip() == "```":
        return "\n".join(lines[1:-1])
    return stripped


def plan_node(state: ImplementationState) -> dict:
    plan_state = run_feature_plan(state["repo_id"], state["feature_description"], state.get("top_k", 25))
    return {
        "plan": plan_state["plan"],
        "risks": plan_state["risks"],
        "context_results": plan_state["context_results"],
    }


def _compute_diff(file_path: str, original: str, new: str) -> str:
    return "".join(
        difflib.unified_diff(
            original.splitlines(keepends=True),
            new.splitlines(keepends=True),
            fromfile=f"a/{file_path}",
            tofile=f"b/{file_path}",
        )
    )


def generate_code_node(state: ImplementationState) -> dict:
    repo_source = get_repo_source(state["repo_id"])
    if repo_source is None:
        return {"proposed_changes": []}

    repo_path = Path(repo_source).expanduser()
    file_paths = sorted({result.file_path for result in state["context_results"]})

    proposed_changes = []
    llm = get_llm_provider()
    for file_path in file_paths:
        target = repo_path / file_path
        if not target.is_file():
            continue

        try:
            original_content = target.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue

        prompt = build_implementation_prompt(state["feature_description"], state["plan"], file_path, original_content)
        raw_response = llm.complete(prompt)
        new_content = _strip_wrapping_code_fence(raw_response) + "\n"

        diff = _compute_diff(file_path, original_content, new_content)
        if not diff:
            continue

        proposed_changes.append(ProposedChange(file_path=file_path, diff=diff, new_content=new_content))

    return {"proposed_changes": proposed_changes}

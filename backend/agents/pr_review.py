"""PR Review Agent: diff a repo's two refs, run grounded checks, then ask
the LLM for additional correctness/security/performance findings.

A bad ref (services.git_diff.GitDiffError) is allowed to propagate — the
caller asked to review a diff between two specific refs, so a missing ref
is a real error to surface, not something to silently paper over.
"""

import re

from pydantic import ValidationError

from prompts.pr_review import build_review_prompt
from services.git_diff import get_changed_files, get_diff
from services.llm import get_llm_provider
from services.repo_registry import get_repo_source
from services.review_signals import check_test_coverage, scan_for_secrets
from state.review_state import ReviewBreakdown, ReviewState

_CODE_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def diff_node(state: ReviewState) -> dict:
    repo_source = get_repo_source(state["repo_id"])
    if repo_source is None:
        return {"diff_text": "", "findings": []}

    diff_text = get_diff(repo_source, state["base_ref"], state["head_ref"])
    changed_files = get_changed_files(repo_source, state["base_ref"], state["head_ref"])

    grounded_findings = scan_for_secrets(diff_text) + check_test_coverage(repo_source, changed_files)

    return {"diff_text": diff_text, "findings": grounded_findings}


def generate_review_node(state: ReviewState) -> dict:
    if not state["diff_text"].strip():
        return {"summary": "No changes found between the given refs.", "findings": state["findings"]}

    grounded_findings = state["findings"]
    prompt = build_review_prompt(state["diff_text"], grounded_findings)
    response = get_llm_provider().complete(prompt, json_mode=True)

    try:
        breakdown = ReviewBreakdown.model_validate_json(_CODE_FENCE_RE.sub("", response).strip())
        return {"summary": breakdown.summary, "findings": grounded_findings + breakdown.findings}
    except ValidationError:
        return {
            "summary": "Automated review findings only — the model's response could not be parsed.",
            "findings": grounded_findings,
        }

"""Engineering Copilot: classify a free-form message into one of the six
existing agents' intents, then dispatch to that agent's own run_*()
function directly — the router never re-implements agent logic, it only
decides which existing one to call.

Dispatch is deliberately read-only/dry-run only: /implement/apply (which
writes files to disk) is never a router target. Applying changes stays a
separate, explicit, human-reviewed call.
"""

import re

from pydantic import ValidationError

from graphs.architecture import run_architecture_explanation
from graphs.code_search import run_code_search
from graphs.feature_planner import run_feature_plan
from graphs.implementation import run_implementation
from graphs.pr_review import run_pr_review
from graphs.ticket_generator import run_generate_tickets
from prompts.router import build_router_prompt
from services.llm import get_llm_provider
from state.router_state import RouterClassification, RouterState

_CODE_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def classify_node(state: RouterState) -> dict:
    prompt = build_router_prompt(state["message"])
    response = get_llm_provider().complete(prompt, json_mode=True)

    try:
        classification = RouterClassification.model_validate_json(_CODE_FENCE_RE.sub("", response).strip())
    except ValidationError:
        classification = RouterClassification(intent="search")

    return {
        "intent": classification.intent,
        "base_ref": classification.base_ref,
        "head_ref": classification.head_ref,
    }


def dispatch_node(state: RouterState) -> dict:
    repo_id = state["repo_id"]
    message = state["message"]
    top_k = state["top_k"]
    intent = state["intent"]

    if intent == "architecture":
        result = run_architecture_explanation(repo_id, message, top_k)
    elif intent == "plan":
        result = run_feature_plan(repo_id, message, top_k)
    elif intent == "tickets":
        result = run_generate_tickets(repo_id, message, top_k)
    elif intent == "implement":
        result = run_implementation(repo_id, message, top_k)
    elif intent == "review":
        base_ref = state["base_ref"] or "main"
        head_ref = state["head_ref"] or "HEAD"
        result = run_pr_review(repo_id, base_ref, head_ref)
    else:
        result = run_code_search(repo_id, message, top_k)

    return {"result": dict(result)}

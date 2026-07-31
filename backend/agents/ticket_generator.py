"""Ticket Generator Agent: run the Phase 5 planner, then break its output into epics/stories/tasks."""

import re

from pydantic import ValidationError

from graphs.feature_planner import run_feature_plan
from prompts.ticket_generator import build_ticket_prompt
from services.llm import get_llm_provider
from state.ticket_state import Epic, Story, TicketBreakdown, TicketGenState

_CODE_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def plan_node(state: TicketGenState) -> dict:
    plan_state = run_feature_plan(state["repo_id"], state["feature_description"], state.get("top_k", 25))
    return {
        "plan": plan_state["plan"],
        "affected_modules": plan_state["affected_modules"],
        "risks": plan_state["risks"],
    }


def _strip_code_fences(text: str) -> str:
    return _CODE_FENCE_RE.sub("", text).strip()


def _fallback_epic(raw_response: str) -> Epic:
    return Epic(
        title="Review generated plan manually",
        description="The model's response could not be parsed as structured ticket JSON; showing it as-is.",
        stories=[
            Story(
                title="Unstructured breakdown",
                description=raw_response,
                acceptance_criteria=[],
                test_cases=[],
                tasks=[],
            )
        ],
    )


def generate_tickets_node(state: TicketGenState) -> dict:
    prompt = build_ticket_prompt(
        state["feature_description"], state["plan"], state["affected_modules"], state["risks"]
    )
    response = get_llm_provider().complete(prompt, json_mode=True)

    try:
        breakdown = TicketBreakdown.model_validate_json(_strip_code_fences(response))
        epics = breakdown.epics
    except ValidationError:
        epics = [_fallback_epic(response)]

    return {"epics": epics}

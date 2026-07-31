"""Feature Planner Agent: retrieve relevant code, analyze impact, then plan."""

from prompts.feature_planner import RISKS_MARKER, build_planner_prompt
from services.hybrid_search import search_repo
from services.impact_analysis import AffectedModule, find_affected_modules
from services.llm import get_llm_provider
from state.feature_planner_state import FeaturePlanState

FAN_IN_RISK_THRESHOLD = 3


def retrieve_node(state: FeaturePlanState) -> dict:
    results = search_repo(state["repo_id"], state["feature_description"], top_k=state.get("top_k", 25))
    return {"context_results": results}


def analyze_impact_node(state: FeaturePlanState) -> dict:
    file_paths = sorted({result.file_path for result in state["context_results"]})
    affected_modules = find_affected_modules(state["repo_id"], file_paths)
    return {"affected_modules": affected_modules}


def _computed_risks(affected_modules: list[AffectedModule]) -> list[str]:
    risks = []
    for module in affected_modules:
        if module.fan_in >= FAN_IN_RISK_THRESHOLD:
            risks.append(
                f"High fan-in: {module.fan_in} other file(s) import {module.file_path} "
                "— changes here have a wide blast radius."
            )
        if module.has_api_endpoint:
            risks.append(
                f"Public API surface: {module.file_path} exposes an API endpoint "
                "— changes may break existing clients."
            )
    return risks


def generate_node(state: FeaturePlanState) -> dict:
    prompt = build_planner_prompt(state["feature_description"], state["context_results"], state["affected_modules"])
    response = get_llm_provider().complete(prompt)

    if RISKS_MARKER in response:
        plan_text, _, risks_text = response.partition(RISKS_MARKER)
    else:
        plan_text, risks_text = response, ""

    llm_risks = [
        line.strip().lstrip("-").strip() for line in risks_text.splitlines() if line.strip().startswith("-")
    ]

    return {
        "plan": plan_text.strip(),
        "risks": _computed_risks(state["affected_modules"]) + llm_risks,
    }

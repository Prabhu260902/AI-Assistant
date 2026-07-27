"""Prompt template for the Feature Planner Agent."""

from services.hybrid_search import SearchResult
from services.impact_analysis import AffectedModule

RISKS_MARKER = "RISKS:"

_SYSTEM_INSTRUCTIONS = (
    "You are a senior software engineer writing an implementation plan for the "
    "feature request below, for the specific repository shown in the code "
    "excerpts and affected-modules list. Ground your plan in that context — "
    "do not invent files, functions, or frameworks not shown.\n\n"
    "Respond in two parts:\n"
    "1. The implementation plan, as a short numbered list of concrete steps.\n"
    f"2. A line containing exactly `{RISKS_MARKER}` followed by any additional "
    "risks you see (beyond the ones already listed under Known signals) as "
    "`- ` bullet points, one per line. If you see no additional risks, write "
    f"`{RISKS_MARKER}` followed by nothing."
)


def build_planner_prompt(
    feature_description: str,
    context_results: list[SearchResult],
    affected_modules: list[AffectedModule],
) -> str:
    context_blocks = []
    for i, result in enumerate(context_results, start=1):
        label = f"[{i}] {result.file_path}:{result.start_line}-{result.end_line}"
        context_blocks.append(f"{label}\n{result.content}")
    context = "\n\n".join(context_blocks) or "(no relevant code excerpts found)"

    module_lines = []
    for module in affected_modules:
        signals = []
        if module.fan_in:
            signals.append(f"{module.fan_in} other file(s) import this")
        if module.has_api_endpoint:
            signals.append("exposes an API endpoint")
        signal_text = f" ({'; '.join(signals)})" if signals else ""
        module_lines.append(f"- {module.file_path} [{module.reason}]{signal_text}")
    modules_text = "\n".join(module_lines) or "(no affected modules found)"

    return (
        f"{_SYSTEM_INSTRUCTIONS}\n\n"
        f"Feature request: {feature_description}\n\n"
        f"Relevant code excerpts:\n\n{context}\n\n"
        f"Known signals (affected modules already identified):\n{modules_text}\n\n"
        "Plan:"
    )

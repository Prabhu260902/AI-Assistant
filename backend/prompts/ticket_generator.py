"""Prompt template for the Ticket Generator Agent."""

from services.impact_analysis import AffectedModule

_JSON_SCHEMA_EXAMPLE = """{
  "epics": [
    {
      "title": "string",
      "description": "string",
      "stories": [
        {
          "title": "string",
          "description": "string",
          "acceptance_criteria": ["string", "..."],
          "test_cases": ["string", "..."],
          "tasks": [
            {"title": "string", "description": "string"}
          ]
        }
      ]
    }
  ]
}"""

_SYSTEM_INSTRUCTIONS = (
    "You are a technical project manager breaking an already-approved implementation "
    "plan into engineering tickets for the repository described below. Ground every "
    "ticket in the plan and affected modules given — do not invent files or scope "
    "beyond them.\n\n"
    "Respond with a single JSON object and nothing else, matching exactly this shape:\n"
    f"{_JSON_SCHEMA_EXAMPLE}\n\n"
    "Group related stories under one or more epics. Each story must have at least one "
    "acceptance criterion and at least one test case. Break each story into concrete "
    "tasks."
)


def build_ticket_prompt(
    feature_description: str,
    plan: str,
    affected_modules: list[AffectedModule],
    risks: list[str],
) -> str:
    module_lines = [f"- {module.file_path} [{module.reason}]" for module in affected_modules]
    modules_text = "\n".join(module_lines) or "(none identified)"

    risks_text = "\n".join(f"- {risk}" for risk in risks) or "(none identified)"

    return (
        f"{_SYSTEM_INSTRUCTIONS}\n\n"
        f"Feature request: {feature_description}\n\n"
        f"Approved implementation plan:\n{plan}\n\n"
        f"Affected modules:\n{modules_text}\n\n"
        f"Known risks:\n{risks_text}\n\n"
        "JSON:"
    )

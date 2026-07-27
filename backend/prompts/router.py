"""Prompt template for the Engineering Copilot's intent router."""

_JSON_SCHEMA_EXAMPLE = """{
  "intent": "search",
  "base_ref": null,
  "head_ref": null
}"""

_SYSTEM_INSTRUCTIONS = (
    "You are an intent router for an engineering assistant. Classify the "
    "developer's message below into exactly one of these intents:\n\n"
    "- search: a general question about specific code, files, or behavior "
    "that doesn't ask for a cross-file flow to be traced.\n"
    "- architecture: asks to explain how something works end-to-end, or to "
    "trace a flow/call path across the system.\n"
    "- plan: wants a written implementation plan for a new feature, and "
    "nothing more.\n"
    "- tickets: wants a feature broken down into epics, stories, or tasks.\n"
    "- implement: wants actual proposed code changes or diffs generated.\n"
    "- review: refers to reviewing a diff, branch, or pull request. If it "
    "names specific branch or ref names, extract them into base_ref and "
    "head_ref; otherwise leave both null.\n\n"
    "If the message doesn't clearly match architecture, plan, tickets, "
    "implement, or review, classify it as search.\n\n"
    "Respond with a single JSON object and nothing else, matching exactly "
    "this shape:\n"
    f"{_JSON_SCHEMA_EXAMPLE}\n\n"
    "base_ref and head_ref must be null unless the intent is review and the "
    "message explicitly names refs."
)


def build_router_prompt(message: str) -> str:
    return f"{_SYSTEM_INSTRUCTIONS}\n\nDeveloper message: {message}\n\nJSON:"

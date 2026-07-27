"""Prompt template for the Implementation Assistant."""

_SYSTEM_INSTRUCTIONS = (
    "You are a senior software engineer implementing an already-approved plan. "
    "You will be given one file's complete current content and must return its "
    "complete new content with the plan's relevant changes applied.\n\n"
    "Respond with ONLY the raw new file content — no markdown code fences, no "
    "explanation, no diff syntax. Preserve everything in the file not related to "
    "this change exactly as-is. If this file genuinely needs no changes for this "
    "plan, return its original content unchanged."
)


def build_implementation_prompt(feature_description: str, plan: str, file_path: str, original_content: str) -> str:
    return (
        f"{_SYSTEM_INSTRUCTIONS}\n\n"
        f"Feature request: {feature_description}\n\n"
        f"Approved implementation plan:\n{plan}\n\n"
        f"File: {file_path}\n"
        f"Current content:\n{original_content}\n\n"
        "New content:"
    )

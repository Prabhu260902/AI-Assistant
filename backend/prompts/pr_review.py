"""Prompt template for the PR Review Agent."""

from state.review_state import Finding

_JSON_SCHEMA_EXAMPLE = """{
  "summary": "string",
  "findings": [
    {
      "category": "correctness" | "security" | "performance" | "test_coverage",
      "severity": "low" | "medium" | "high",
      "file_path": "string",
      "line": 123,
      "description": "string"
    }
  ]
}"""

_SYSTEM_INSTRUCTIONS = (
    "You are a senior software engineer reviewing a diff for correctness, "
    "security, performance, and test coverage. Some findings have already "
    "been identified by automated checks (listed below) — do not repeat "
    "them; focus on additional issues only a careful reader would catch. "
    "Base findings only on what the diff actually shows; don't speculate "
    "about code you can't see.\n\n"
    "Respond with a single JSON object and nothing else, matching exactly this shape:\n"
    f"{_JSON_SCHEMA_EXAMPLE}"
)


def build_review_prompt(diff_text: str, grounded_findings: list[Finding]) -> str:
    grounded_text = "\n".join(
        f"- [{f.category}/{f.severity}] {f.file_path}"
        + (f":{f.line}" if f.line is not None else "")
        + f" — {f.description}"
        for f in grounded_findings
    ) or "(none)"

    return (
        f"{_SYSTEM_INSTRUCTIONS}\n\n"
        f"Already-identified findings (do not repeat these):\n{grounded_text}\n\n"
        f"Diff:\n{diff_text}\n\n"
        "JSON:"
    )

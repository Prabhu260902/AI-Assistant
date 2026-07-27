"""Grounded (non-LLM) PR review signals: secret-shaped strings added in the
diff, and changed files with no plausible matching test file on disk.

Same "detect obviously risky patterns without an LLM call" philosophy as
Phase 2's filename-based secret denylist (services.ingest._is_secret_file),
applied here to diff line content and to a test-coverage heuristic instead.
"""

import re
from pathlib import Path

from state.review_state import Finding

_SECRET_PATTERNS = [
    re.compile(r"(?i)(api[_-]?key|secret|token|password)\s*[:=]\s*['\"][A-Za-z0-9\-_.]{16,}['\"]"),
    re.compile(r"AKIA[0-9A-Z]{16}"),  # AWS access key id shape
    re.compile(r"(?i)bearer\s+[A-Za-z0-9\-_.]{20,}"),
]

_TEST_DIRS = ("tests", "test", "__tests__")
_TEST_EXTENSIONS_BY_SOURCE_EXT = {
    ".py": [".py"],
    ".js": [".js", ".jsx", ".ts", ".tsx"],
    ".jsx": [".js", ".jsx", ".ts", ".tsx"],
    ".ts": [".js", ".jsx", ".ts", ".tsx"],
    ".tsx": [".js", ".jsx", ".ts", ".tsx"],
}


def scan_for_secrets(diff_text: str) -> list[Finding]:
    findings = []
    file_path = None
    line_number = 0

    for line in diff_text.splitlines():
        if line.startswith("+++ "):
            raw_path = line[len("+++ ") :]
            file_path = raw_path[2:] if raw_path.startswith("b/") else raw_path
            continue
        if line.startswith("---"):
            continue
        if line.startswith("@@"):
            match = re.search(r"\+(\d+)", line)
            line_number = int(match.group(1)) - 1 if match else 0
            continue
        if line.startswith("+"):
            line_number += 1
            content = line[1:]
            if any(pattern.search(content) for pattern in _SECRET_PATTERNS):
                findings.append(
                    Finding(
                        category="security",
                        severity="high",
                        file_path=file_path or "unknown",
                        line=line_number,
                        description=f"Added line looks like it introduces a hardcoded secret/credential: {content.strip()[:120]}",
                    )
                )
        elif line.startswith("-"):
            continue
        else:
            line_number += 1

    return findings


def _looks_like_test_file(path: Path) -> bool:
    name = path.name.lower()
    return (
        name.startswith("test_")
        or name.endswith("_test" + path.suffix)
        or ".test." in name
        or ".spec." in name
        or any(part in _TEST_DIRS for part in path.parts)
    )


def _test_filename_candidates(stem: str, ext: str) -> list[str]:
    names = []
    for candidate_ext in _TEST_EXTENSIONS_BY_SOURCE_EXT.get(ext, [ext]):
        names.extend([f"test_{stem}{candidate_ext}", f"{stem}_test{candidate_ext}", f"{stem}.test{candidate_ext}", f"{stem}.spec{candidate_ext}"])
    return names


def check_test_coverage(repo_path: str, changed_files: list[str]) -> list[Finding]:
    base = Path(repo_path).expanduser()
    findings = []

    for file_path in changed_files:
        path = Path(file_path)
        if _looks_like_test_file(path):
            continue

        candidate_names = _test_filename_candidates(path.stem, path.suffix)
        candidate_rel_paths = [path.parent / name for name in candidate_names]
        for test_dir in _TEST_DIRS:
            candidate_rel_paths.extend(path.parent / test_dir / name for name in candidate_names)

        if not any((base / rel).is_file() for rel in candidate_rel_paths):
            findings.append(
                Finding(
                    category="test_coverage",
                    severity="medium",
                    file_path=file_path,
                    line=None,
                    description=f"No matching test file found for '{file_path}' — checked common naming/location conventions.",
                )
            )

    return findings

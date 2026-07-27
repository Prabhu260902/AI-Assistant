"""Apply LLM-proposed code changes to a local repository, gated behind git
branch isolation and a clean-working-tree check.

Never commits — writes land as uncommitted changes on a new branch, leaving
the actual `git commit` as a manual human step.
"""

import subprocess
from dataclasses import dataclass
from pathlib import Path


class ApplyError(Exception):
    """Raised when it's unsafe or invalid to apply changes."""


@dataclass
class FileChange:
    file_path: str
    new_content: str


@dataclass
class ApplySummary:
    branch: str
    files_written: list[str]


def _run_git(repo_path: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=repo_path,
        check=True,
        capture_output=True,
        text=True,
    )


def apply_changes(repo_source: str, changes: list[FileChange], branch_name: str) -> ApplySummary:
    repo_path = Path(repo_source).expanduser()
    if not repo_path.is_dir():
        raise ApplyError(f"'{repo_source}' is not an existing local directory — apply requires a local repo path")
    repo_path = repo_path.resolve()

    try:
        status = _run_git(repo_path, "status", "--porcelain")
    except subprocess.CalledProcessError as exc:
        raise ApplyError(f"'{repo_source}' does not look like a git repository: {exc.stderr.strip()}") from exc

    if status.stdout.strip():
        raise ApplyError(
            f"Working tree at '{repo_source}' is not clean — commit or stash existing changes before applying"
        )

    existing_branches = _run_git(repo_path, "branch", "--list", branch_name).stdout.strip()
    if existing_branches:
        raise ApplyError(f"Branch '{branch_name}' already exists — choose a different name")

    try:
        _run_git(repo_path, "checkout", "-b", branch_name)
    except subprocess.CalledProcessError as exc:
        raise ApplyError(f"Could not create branch '{branch_name}': {exc.stderr.strip()}") from exc

    files_written = []
    for change in changes:
        target = (repo_path / change.file_path).resolve()
        if target != repo_path and repo_path not in target.parents:
            raise ApplyError(f"'{change.file_path}' resolves outside the repository — refusing to write")
        if not target.is_file():
            raise ApplyError(
                f"'{change.file_path}' does not exist in the repo — apply only supports editing existing files"
            )
        target.write_text(change.new_content, encoding="utf-8")
        files_written.append(change.file_path)

    return ApplySummary(branch=branch_name, files_written=files_written)

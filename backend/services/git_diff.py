"""Compute diffs between two git refs in a local repository (read-only —
never writes; see services.code_apply for the write path)."""

import subprocess
from pathlib import Path


class GitDiffError(Exception):
    """Raised when two refs can't be diffed (e.g. a ref doesn't exist)."""


def _run_git(repo_path: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=repo_path,
        check=True,
        capture_output=True,
        text=True,
    )


def get_diff(repo_source: str, base_ref: str, head_ref: str) -> str:
    """Unified diff for `head_ref` relative to where it diverged from
    `base_ref` (three-dot range — matches how GitHub computes a PR diff)."""
    repo_path = Path(repo_source).expanduser()
    try:
        result = _run_git(repo_path, "diff", f"{base_ref}...{head_ref}")
    except subprocess.CalledProcessError as exc:
        raise GitDiffError(
            f"Could not diff '{base_ref}...{head_ref}' in '{repo_source}': {exc.stderr.strip()}"
        ) from exc
    return result.stdout


def get_changed_files(repo_source: str, base_ref: str, head_ref: str) -> list[str]:
    repo_path = Path(repo_source).expanduser()
    try:
        result = _run_git(repo_path, "diff", "--name-only", f"{base_ref}...{head_ref}")
    except subprocess.CalledProcessError as exc:
        raise GitDiffError(
            f"Could not diff '{base_ref}...{head_ref}' in '{repo_source}': {exc.stderr.strip()}"
        ) from exc
    return [line for line in result.stdout.splitlines() if line]

"""Resolve a repository source (local path or git URL) into a local directory.

Callers pass either an existing local path (read in place) or a git URL
(shallow-cloned into a temp directory via the system `git` binary — no
extra HTTP/git dependency needed).
"""

import re
import subprocess
import tempfile
from pathlib import Path

_GIT_URL_PATTERN = re.compile(r"^(https?://|git@|ssh://)")


def is_git_url(source: str) -> bool:
    return bool(_GIT_URL_PATTERN.match(source)) or source.endswith(".git")


def resolve_repo(source: str) -> Path:
    local_path = Path(source).expanduser()
    if local_path.exists():
        return local_path.resolve()

    if not is_git_url(source):
        raise ValueError(f"'{source}' is neither an existing local path nor a recognizable git URL")

    dest = Path(tempfile.mkdtemp(prefix="repo-ingest-"))
    subprocess.run(
        ["git", "clone", "--depth", "1", source, str(dest)],
        check=True,
        capture_output=True,
        text=True,
    )
    return dest


def derive_repo_id(source: str) -> str:
    name = Path(source.rstrip("/")).stem or "repo"
    sanitized = re.sub(r"[^a-zA-Z0-9_-]", "-", name).strip("-_").lower()
    sanitized = (sanitized or "repo")[:63].strip("-_") or "repo"
    if len(sanitized) < 3:
        sanitized = f"repo-{sanitized}"
    return sanitized[:63]

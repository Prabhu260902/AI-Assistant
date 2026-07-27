"""Look up an ingested repo's local source path (Phase 3's Repository table).

Shared by any agent that needs to operate on a repo's real files on disk —
Phase 7's Implementation Assistant and Phase 8's PR Review Agent both do.
"""

from sqlalchemy import select

from services.db import session_scope
from services.models import Repository


def get_repo_source(repo_id: str) -> str | None:
    with session_scope() as session:
        repository = session.execute(select(Repository).where(Repository.repo_id == repo_id)).scalar_one_or_none()
        return repository.source if repository else None

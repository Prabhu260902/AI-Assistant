"""Impact analysis over the Phase 3 knowledge graph: given a set of directly
relevant files, find other files that likely depend on them.

Phase 3's `Call.callee_symbol_id` only resolves same-file calls, so it can't
answer "who calls into file X from file Y" — this uses the `imports` table
instead, via a fragment/substring heuristic (not exact import resolution):
a file's name fragments (e.g. `hcps`, `routers.hcps` for
`backend/routers/hcps.py`) are searched for in other files' stored import
text. Disclosed heuristic, same spirit as Phase 3's own resolution logic.
"""

from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import or_, select

from services.db import session_scope
from services.models import ApiEndpoint, File, Import, Repository

MIN_FRAGMENT_LENGTH = 3


@dataclass
class AffectedModule:
    file_path: str
    reason: str
    fan_in: int
    has_api_endpoint: bool


def _fragments_for(file_path: str) -> list[str]:
    path = Path(file_path)
    stem = path.stem
    fragments = set()
    if len(stem) >= MIN_FRAGMENT_LENGTH:
        fragments.add(stem)
    if path.parent != Path("."):
        dotted = f"{path.parent.name}.{stem}"
        if len(dotted) >= MIN_FRAGMENT_LENGTH:
            fragments.add(dotted)
    return list(fragments)


def _find_dependents(session, repository_id: int, target_file_id: int, fragments: list[str]) -> set[str]:
    if not fragments:
        return set()

    conditions = []
    for fragment in fragments:
        conditions.append(Import.module_path.ilike(f"%{fragment}%"))
        conditions.append(Import.raw_source.ilike(f"%{fragment}%"))

    stmt = (
        select(File.file_path)
        .join(Import, Import.file_id == File.id)
        .where(File.repository_id == repository_id, File.id != target_file_id, or_(*conditions))
        .distinct()
    )
    return set(session.execute(stmt).scalars().all())


def find_affected_modules(repo_id: str, direct_file_paths: list[str]) -> list[AffectedModule]:
    with session_scope() as session:
        repository = session.execute(
            select(Repository).where(Repository.repo_id == repo_id)
        ).scalar_one_or_none()
        if repository is None:
            return []

        files_by_path = {
            f.file_path: f
            for f in session.execute(select(File).where(File.repository_id == repository.id)).scalars().all()
        }

        reasons: dict[str, str] = {}
        for file_path in direct_file_paths:
            if file_path in files_by_path:
                reasons[file_path] = "directly relevant"

        for file_path in direct_file_paths:
            target = files_by_path.get(file_path)
            if target is None:
                continue
            dependents = _find_dependents(session, repository.id, target.id, _fragments_for(file_path))
            for dependent_path in dependents:
                reasons.setdefault(dependent_path, f"imports {file_path}")

        results = []
        for file_path, reason in reasons.items():
            file_row = files_by_path.get(file_path)
            if file_row is None:
                continue

            fan_in = len(_find_dependents(session, repository.id, file_row.id, _fragments_for(file_path)))
            has_endpoint = (
                session.execute(
                    select(ApiEndpoint.id).where(ApiEndpoint.file_id == file_row.id).limit(1)
                ).first()
                is not None
            )
            results.append(
                AffectedModule(file_path=file_path, reason=reason, fan_in=fan_in, has_api_endpoint=has_endpoint)
            )

        return results

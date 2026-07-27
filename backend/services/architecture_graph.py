"""Build a grounded call-graph flow diagram from a starting point, using
Phase 3's knowledge graph (calls, symbols, api_endpoints, imports) — never
LLM-generated, so the resulting diagram can't hallucinate a relationship
that isn't actually in the data.

Phase 3's `Call.callee_symbol_id` only resolves same-file calls; a
cross-file hop is attempted via the same import-fragment heuristic
`impact_analysis.py` uses, in the forward direction this time — "what does
this file's import likely refer to" rather than "who imports this file".
Anything that can't be resolved either way is shown as an external leaf
node labeled with the raw call text, not hidden or guessed at further.
"""

from dataclasses import dataclass, field

from sqlalchemy import select

from services.db import session_scope
from services.import_resolution import fragments_for
from services.models import ApiEndpoint, Call, File, Import, Repository, Symbol

DEFAULT_MAX_DEPTH = 3
DEFAULT_MAX_NODES = 25


@dataclass
class FlowNode:
    key: str
    name: str
    file_path: str
    kind: str  # "endpoint" | "function" | "external"
    detail: str | None = None


@dataclass
class FlowEdge:
    from_key: str
    to_key: str


@dataclass
class FlowGraph:
    nodes: list[FlowNode] = field(default_factory=list)
    edges: list[FlowEdge] = field(default_factory=list)


def _symbol_key(symbol_id: int) -> str:
    return f"symbol:{symbol_id}"


def find_starting_point(
    repo_id: str, file_path: str, start_line: int, end_line: int | None = None
) -> tuple[int, FlowNode] | None:
    """Resolve a hybrid-search hit's line range to the symbol it falls in.

    Uses range *overlap*, not "symbol contains the hit's start line" — a
    retrieved chunk's start line can land just before a function's actual
    `start_line` (e.g. a chunk beginning mid-file at the tail of the
    previous function) while still substantially overlapping it, and an
    exact-containment check on the start line alone missed that case
    against a real repo during verification.
    """
    end_line = end_line if end_line is not None else start_line

    with session_scope() as session:
        repository = session.execute(select(Repository).where(Repository.repo_id == repo_id)).scalar_one_or_none()
        if repository is None:
            return None

        file_row = session.execute(
            select(File).where(File.repository_id == repository.id, File.file_path == file_path)
        ).scalar_one_or_none()
        if file_row is None:
            return None

        symbol = (
            session.execute(
                select(Symbol)
                .where(Symbol.file_id == file_row.id, Symbol.start_line <= end_line, Symbol.end_line >= start_line)
                .order_by(Symbol.end_line - Symbol.start_line)
            )
            .scalars()
            .first()
        )
        if symbol is None:
            return None

        endpoint = session.execute(
            select(ApiEndpoint).where(ApiEndpoint.handler_symbol_id == symbol.id)
        ).scalar_one_or_none()

        if endpoint is not None:
            node = FlowNode(
                key=_symbol_key(symbol.id),
                name=symbol.name,
                file_path=file_path,
                kind="endpoint",
                detail=f"{endpoint.method} {endpoint.path}",
            )
        else:
            node = FlowNode(key=_symbol_key(symbol.id), name=symbol.name, file_path=file_path, kind="function")

        return symbol.id, node


def _try_cross_file_hop(session, repository_id: int, caller_file_path: str, callee_name: str) -> Symbol | None:
    caller_file = session.execute(
        select(File).where(File.repository_id == repository_id, File.file_path == caller_file_path)
    ).scalar_one_or_none()
    if caller_file is None:
        return None

    imports = session.execute(select(Import).where(Import.file_id == caller_file.id)).scalars().all()
    if not imports:
        return None

    other_files = (
        session.execute(select(File).where(File.repository_id == repository_id, File.id != caller_file.id))
        .scalars()
        .all()
    )

    candidate_file_ids = []
    for other_file in other_files:
        frags = fragments_for(other_file.file_path)
        if not frags:
            continue
        if any(frag in f"{imp.module_path or ''} {imp.raw_source}" for frag in frags for imp in imports):
            candidate_file_ids.append(other_file.id)

    if not candidate_file_ids:
        return None

    matches = (
        session.execute(select(Symbol).where(Symbol.file_id.in_(candidate_file_ids), Symbol.name == callee_name))
        .scalars()
        .all()
    )
    return matches[0] if len(matches) == 1 else None


def _calls_within_symbol(session, symbol: Symbol) -> list[Call]:
    """Calls textually inside `symbol`'s own line range.

    Phase 3's `Call.caller_symbol_id` is never actually populated (its
    extraction only determines the callee side) — confirmed empty across
    every call in a real ingested repo during this phase's verification.
    Rather than depend on a column that's always NULL, or touch Phase 3's
    extraction code, this recomputes "which calls belong to this symbol" at
    query time via the same range logic `find_starting_point` uses. Doesn't
    exclude calls that are actually inside a *nested* symbol defined within
    this one's range — a disclosed simplification, not full scope analysis.
    """
    return (
        session.execute(
            select(Call).where(
                Call.file_id == symbol.file_id,
                Call.start_line >= symbol.start_line,
                Call.start_line <= symbol.end_line,
            )
        )
        .scalars()
        .all()
    )


def build_flow_graph(
    repo_id: str,
    start_symbol_id: int,
    start_node: FlowNode,
    max_depth: int = DEFAULT_MAX_DEPTH,
    max_nodes: int = DEFAULT_MAX_NODES,
) -> FlowGraph:
    with session_scope() as session:
        repository = session.execute(select(Repository).where(Repository.repo_id == repo_id)).scalar_one_or_none()
        if repository is None:
            return FlowGraph(nodes=[start_node], edges=[])

        nodes: dict[str, FlowNode] = {start_node.key: start_node}
        edges: list[FlowEdge] = []
        visited_symbol_ids: set[int] = {start_symbol_id}
        queue: list[tuple[int, FlowNode, int]] = [(start_symbol_id, start_node, 0)]
        external_counter = 0

        while queue and len(nodes) < max_nodes:
            symbol_id, node, depth = queue.pop(0)
            if depth >= max_depth:
                continue

            current_symbol = session.get(Symbol, symbol_id)
            if current_symbol is None:
                continue

            calls = _calls_within_symbol(session, current_symbol)
            for call in calls:
                if len(nodes) >= max_nodes:
                    break

                target_symbol = (
                    session.get(Symbol, call.callee_symbol_id)
                    if call.callee_symbol_id is not None
                    else _try_cross_file_hop(session, repository.id, node.file_path, call.callee_name)
                )

                if target_symbol is not None:
                    target_key = _symbol_key(target_symbol.id)
                    if target_key not in nodes:
                        target_file = session.get(File, target_symbol.file_id)
                        target_node = FlowNode(
                            key=target_key,
                            name=target_symbol.name,
                            file_path=target_file.file_path if target_file else "",
                            kind="function",
                        )
                        nodes[target_key] = target_node
                        if target_symbol.id not in visited_symbol_ids:
                            visited_symbol_ids.add(target_symbol.id)
                            queue.append((target_symbol.id, target_node, depth + 1))
                    edges.append(FlowEdge(from_key=node.key, to_key=target_key))
                    continue

                external_counter += 1
                external_key = f"external:{external_counter}"
                nodes[external_key] = FlowNode(
                    key=external_key, name=call.callee_name, file_path=node.file_path, kind="external"
                )
                edges.append(FlowEdge(from_key=node.key, to_key=external_key))

        return FlowGraph(nodes=list(nodes.values()), edges=edges)

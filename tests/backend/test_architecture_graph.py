import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from services.architecture_graph import build_flow_graph, find_starting_point
from services.models import ApiEndpoint, Base, Call, File, Import, Repository, Symbol


@pytest.fixture
def sqlite_engine(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    monkeypatch.setattr("services.db.get_engine", lambda: engine)
    Base.metadata.create_all(engine)
    return engine


def _seed_basic_graph(engine):
    with Session(engine) as session:
        repo = Repository(repo_id="arch-test-repo", source="/tmp/x")
        session.add(repo)
        session.flush()

        f_hcps = File(repository_id=repo.id, file_path="backend/routers/hcps.py", language="python")
        f_db = File(repository_id=repo.id, file_path="backend/database.py", language="python")
        session.add_all([f_hcps, f_db])
        session.flush()

        sym_create = Symbol(file_id=f_hcps.id, name="create_hcp", kind="Function", start_line=10, end_line=15)
        sym_helper = Symbol(file_id=f_hcps.id, name="validate_hcp", kind="Function", start_line=20, end_line=25)
        sym_get_db = Symbol(file_id=f_db.id, name="get_db", kind="Function", start_line=1, end_line=5)
        session.add_all([sym_create, sym_helper, sym_get_db])
        session.flush()

        session.add(
            ApiEndpoint(
                file_id=f_hcps.id,
                method="POST",
                path="/hcps",
                handler_symbol_id=sym_create.id,
                framework_hint="fastapi_flask",
                start_line=10,
            )
        )
        session.add(
            Call(
                file_id=f_hcps.id,
                caller_symbol_id=sym_create.id,
                callee_name="validate_hcp",
                callee_symbol_id=sym_helper.id,
                start_line=11,
            )
        )
        session.add(
            Call(
                file_id=f_hcps.id,
                caller_symbol_id=sym_create.id,
                callee_name="get_db",
                callee_symbol_id=None,
                start_line=12,
            )
        )
        session.add(
            Call(
                file_id=f_hcps.id,
                caller_symbol_id=sym_create.id,
                callee_name="db.commit",
                callee_symbol_id=None,
                start_line=13,
            )
        )
        session.add(
            Import(file_id=f_hcps.id, raw_source="from database import get_db", module_path="database", start_line=1)
        )
        session.commit()
        return sym_create.id


def test_find_starting_point_resolves_line_to_containing_symbol(sqlite_engine):
    _seed_basic_graph(sqlite_engine)

    result = find_starting_point("arch-test-repo", "backend/routers/hcps.py", 12)

    assert result is not None
    symbol_id, node = result
    assert node.name == "create_hcp"
    assert node.kind == "endpoint"
    assert node.detail == "POST /hcps"


def test_find_starting_point_labels_non_endpoint_as_function(sqlite_engine):
    _seed_basic_graph(sqlite_engine)

    result = find_starting_point("arch-test-repo", "backend/routers/hcps.py", 22)

    assert result is not None
    _, node = result
    assert node.name == "validate_hcp"
    assert node.kind == "function"


def test_find_starting_point_returns_none_for_unknown_repo(sqlite_engine):
    assert find_starting_point("no-such-repo", "a.py", 1) is None


def test_find_starting_point_matches_on_range_overlap_not_just_start_line(sqlite_engine):
    """Regression test: caught by real-repo verification against hcp-crm —
    a retrieved chunk [129, 170] overlaps a real symbol [130, 168], but the
    original exact-containment check on the chunk's start line alone
    (129 <= 130 is false at the boundary) missed it entirely."""
    _seed_basic_graph(sqlite_engine)

    # create_hcp spans [10, 15]; a chunk starting one line earlier (mirrors
    # a chunk boundary landing just before the function's own start_line)
    # must still resolve to it via overlap, not exact start-line containment.
    result = find_starting_point("arch-test-repo", "backend/routers/hcps.py", 9, 12)

    assert result is not None
    _, node = result
    assert node.name == "create_hcp"


def test_build_flow_graph_works_when_caller_symbol_id_is_never_set(sqlite_engine):
    """Regression test: real-repo verification against hcp-crm found
    Call.caller_symbol_id is NEVER actually populated by Phase 3's
    extraction (confirmed: 0 of 566 real calls had it set) — traversal
    must work from call.start_line falling within the caller's own range,
    not from a column that in practice is always NULL."""
    with Session(sqlite_engine) as session:
        repo = Repository(repo_id="null-caller-repo", source="/tmp/x")
        session.add(repo)
        session.flush()

        f = File(repository_id=repo.id, file_path="app.py", language="python")
        session.add(f)
        session.flush()

        sym_a = Symbol(file_id=f.id, name="handler", kind="Function", start_line=10, end_line=20)
        sym_b = Symbol(file_id=f.id, name="helper", kind="Function", start_line=30, end_line=35)
        session.add_all([sym_a, sym_b])
        session.flush()

        # caller_symbol_id intentionally left unset, matching real Phase 3 data
        session.add(
            Call(file_id=f.id, caller_symbol_id=None, callee_name="helper", callee_symbol_id=sym_b.id, start_line=12)
        )
        session.commit()
        start_id = sym_a.id

    _, start_node = find_starting_point("null-caller-repo", "app.py", 10, 20)
    graph = build_flow_graph("null-caller-repo", start_id, start_node)

    assert any(n.name == "helper" for n in graph.nodes)


def test_build_flow_graph_follows_same_file_call(sqlite_engine):
    start_symbol_id = _seed_basic_graph(sqlite_engine)
    _, start_node = find_starting_point("arch-test-repo", "backend/routers/hcps.py", 12)

    graph = build_flow_graph("arch-test-repo", start_symbol_id, start_node)

    names_by_kind = {n.kind: [] for n in graph.nodes}
    for n in graph.nodes:
        names_by_kind[n.kind].append(n.name)

    assert "validate_hcp" in names_by_kind["function"]


def test_build_flow_graph_hops_cross_file_via_import_fragment(sqlite_engine):
    start_symbol_id = _seed_basic_graph(sqlite_engine)
    _, start_node = find_starting_point("arch-test-repo", "backend/routers/hcps.py", 12)

    graph = build_flow_graph("arch-test-repo", start_symbol_id, start_node)

    hop_node = next((n for n in graph.nodes if n.name == "get_db"), None)
    assert hop_node is not None
    assert hop_node.kind == "function"
    assert hop_node.file_path == "backend/database.py"


def test_build_flow_graph_shows_unresolved_call_as_external_leaf(sqlite_engine):
    start_symbol_id = _seed_basic_graph(sqlite_engine)
    _, start_node = find_starting_point("arch-test-repo", "backend/routers/hcps.py", 12)

    graph = build_flow_graph("arch-test-repo", start_symbol_id, start_node)

    external_node = next((n for n in graph.nodes if n.name == "db.commit"), None)
    assert external_node is not None
    assert external_node.kind == "external"


def test_build_flow_graph_respects_max_depth(sqlite_engine):
    with Session(sqlite_engine) as session:
        repo = Repository(repo_id="chain-repo", source="/tmp/x")
        session.add(repo)
        session.flush()

        f = File(repository_id=repo.id, file_path="chain.py", language="python")
        session.add(f)
        session.flush()

        symbols = [Symbol(file_id=f.id, name=f"fn{i}", kind="Function", start_line=i * 10, end_line=i * 10 + 5) for i in range(4)]
        session.add_all(symbols)
        session.flush()

        for i in range(3):
            session.add(
                Call(
                    file_id=f.id,
                    caller_symbol_id=symbols[i].id,
                    callee_name=f"fn{i + 1}",
                    callee_symbol_id=symbols[i + 1].id,
                    start_line=i * 10 + 1,
                )
            )
        session.commit()
        start_id = symbols[0].id

    _, start_node = find_starting_point("chain-repo", "chain.py", 1)
    graph = build_flow_graph("chain-repo", start_id, start_node, max_depth=2)

    names = {n.name for n in graph.nodes}
    assert names == {"fn0", "fn1", "fn2"}  # fn3 is one hop past the depth limit

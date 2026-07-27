"""Repository knowledge graph extraction: imports, symbols, call graph,
and API endpoints, persisted to Postgres.

Imports/symbols use `tree_sitter_language_pack.process()`, which works
generically across languages. Call-graph and API-endpoint detection use
direct low-level tree-sitter queries and are scoped to Python (decorator
style: `@router.get("/path")`) and JavaScript/TypeScript/TSX (call style:
`app.get("/path", handler)`), filtered to a known HTTP-verb allowlist to
avoid false positives from unrelated decorators/calls.

Call/endpoint handler resolution is a same-file name match against known
symbols — a heuristic, not full semantic/import resolution (an unresolved
match, e.g. a call into a third-party library, is expected and left NULL).
"""

import re
from dataclasses import dataclass, field

import tree_sitter
import tree_sitter_language_pack as tslp
from sqlalchemy import select

from services.db import create_all, session_scope
from services.ingest import _is_secret_file, _iter_source_files, _read_text
from services.models import ApiEndpoint, Call, File, Import, Repository, Symbol
from services.repo_loader import derive_repo_id, resolve_repo

HTTP_VERBS = {"get", "post", "put", "patch", "delete", "head", "options"}

_PY_CALL_QUERY = """
(call function: (identifier) @callee)
(call function: (attribute attribute: (identifier) @callee))
"""

_JS_CALL_QUERY = """
(call_expression function: (identifier) @callee)
(call_expression function: (member_expression property: (property_identifier) @callee))
"""

_PY_ENDPOINT_QUERY = """
(decorated_definition
  (decorator (call
    function: (attribute object: (identifier) @obj attribute: (identifier) @verb)
    arguments: (argument_list (string) @path)))
  definition: (function_definition name: (identifier) @handler))
"""

_JS_ENDPOINT_QUERY = """
(call_expression
  function: (member_expression object: (identifier) @obj property: (property_identifier) @verb)
  arguments: (arguments (string (string_fragment) @path) . (_) @handler_arg))
"""

CALL_QUERIES = {
    "python": _PY_CALL_QUERY,
    "javascript": _JS_CALL_QUERY,
    "typescript": _JS_CALL_QUERY,
    "tsx": _JS_CALL_QUERY,
}
ENDPOINT_QUERIES = {
    "python": _PY_ENDPOINT_QUERY,
    "javascript": _JS_ENDPOINT_QUERY,
    "typescript": _JS_ENDPOINT_QUERY,
    "tsx": _JS_ENDPOINT_QUERY,
}
_FRAMEWORK_HINT = {
    "python": "fastapi_flask",
    "javascript": "express",
    "typescript": "express",
    "tsx": "express",
}

_PY_IMPORT_RE = re.compile(r"^\s*(?:from\s+([\w.]+)\s+import|import\s+([\w.]+))")
_JS_IMPORT_RE = re.compile(r"""['"]([^'"]+)['"]""")

_query_cache: dict[tuple[str, str], "tree_sitter.Query"] = {}


def _compiled_query(language: str, query_str: str) -> "tree_sitter.Query":
    key = (language, query_str)
    if key not in _query_cache:
        _query_cache[key] = tree_sitter.Query(tslp.get_language(language), query_str)
    return _query_cache[key]


def _parse_module_path(raw_source: str, language: str) -> str | None:
    if language == "python":
        match = _PY_IMPORT_RE.match(raw_source)
        if match:
            return match.group(1) or match.group(2)
        return None
    if language in ("javascript", "typescript", "tsx"):
        match = _JS_IMPORT_RE.search(raw_source)
        return match.group(1) if match else None
    return None


@dataclass
class ImportRecord:
    raw_source: str
    module_path: str | None
    start_line: int


@dataclass
class SymbolRecord:
    name: str
    kind: str
    start_line: int
    end_line: int


@dataclass
class CallRecord:
    callee_name: str
    start_line: int


@dataclass
class EndpointRecord:
    method: str
    path: str
    handler_name: str | None
    framework_hint: str
    start_line: int


@dataclass
class FileGraph:
    imports: list[ImportRecord] = field(default_factory=list)
    symbols: list[SymbolRecord] = field(default_factory=list)
    calls: list[CallRecord] = field(default_factory=list)
    endpoints: list[EndpointRecord] = field(default_factory=list)


def extract_file_graph(text: str, language: str | None) -> FileGraph:
    graph = FileGraph()
    if not language:
        return graph

    try:
        result = tslp.process(
            text,
            tslp.ProcessConfig(language=language, structure=False, imports=True, exports=False, symbols=True),
        )
        for raw_import in result.imports or []:
            graph.imports.append(
                ImportRecord(
                    raw_source=raw_import.source,
                    module_path=_parse_module_path(raw_import.source, language),
                    start_line=raw_import.span.start_line + 1,
                )
            )
        for raw_symbol in result.symbols or []:
            graph.symbols.append(
                SymbolRecord(
                    name=raw_symbol.name,
                    kind=str(raw_symbol.kind),
                    start_line=raw_symbol.span.start_line + 1,
                    end_line=raw_symbol.span.end_line + 1,
                )
            )
    except Exception:
        pass

    if language in CALL_QUERIES:
        try:
            parser = tslp.get_parser(language)
            tree = parser.parse(text.encode("utf-8"))
            graph.calls = _extract_calls(tree, text, language)
            graph.endpoints = _extract_endpoints(tree, text, language)
        except Exception:
            pass

    return graph


def _line_number(encoded: bytes, byte_offset: int) -> int:
    """1-indexed line containing the given UTF-8 byte offset.

    Deliberately avoids tree-sitter `Node.start_point` — empirically found to
    be an unstable code path in this tree-sitter/tree-sitter-language-pack
    version combination (intermittent native segfaults on real-world files;
    see docs/phase3.md). `start_byte`/`end_byte` access is stable.
    """
    return encoded.count(b"\n", 0, byte_offset) + 1


def _extract_calls(tree, text: str, language: str) -> list[CallRecord]:
    query = _compiled_query(language, CALL_QUERIES[language])
    cursor = tree_sitter.QueryCursor(query)
    captures = cursor.captures(tree.root_node)
    encoded = text.encode("utf-8")

    calls = []
    for nodes in captures.values():
        for node in nodes:
            name = encoded[node.start_byte : node.end_byte].decode("utf-8", errors="replace")
            calls.append(CallRecord(callee_name=name, start_line=_line_number(encoded, node.start_byte)))
    return calls


def _extract_endpoints(tree, text: str, language: str) -> list[EndpointRecord]:
    query = _compiled_query(language, ENDPOINT_QUERIES[language])
    cursor = tree_sitter.QueryCursor(query)
    matches = cursor.matches(tree.root_node)
    encoded = text.encode("utf-8")
    framework_hint = _FRAMEWORK_HINT[language]

    endpoints = []
    for _, captures in matches:
        verb_nodes = captures.get("verb")
        path_nodes = captures.get("path")
        if not verb_nodes or not path_nodes:
            continue

        verb = encoded[verb_nodes[0].start_byte : verb_nodes[0].end_byte].decode().lower()
        if verb not in HTTP_VERBS:
            continue

        path_text = encoded[path_nodes[0].start_byte : path_nodes[0].end_byte].decode("utf-8", errors="replace")
        path_text = path_text.strip("'\"")

        handler_name = None
        if language == "python":
            handler_nodes = captures.get("handler")
            if handler_nodes:
                handler_name = encoded[handler_nodes[0].start_byte : handler_nodes[0].end_byte].decode()
        else:
            handler_nodes = captures.get("handler_arg")
            if handler_nodes and handler_nodes[0].type == "identifier":
                handler_name = encoded[handler_nodes[0].start_byte : handler_nodes[0].end_byte].decode()

        endpoints.append(
            EndpointRecord(
                method=verb.upper(),
                path=path_text,
                handler_name=handler_name,
                framework_hint=framework_hint,
                start_line=_line_number(encoded, verb_nodes[0].start_byte),
            )
        )
    return endpoints


@dataclass
class KnowledgeGraphSummary:
    repo_id: str
    files: int = 0
    symbols: int = 0
    imports: int = 0
    calls: int = 0
    endpoints: int = 0


def build_knowledge_graph(source: str, repo_id: str | None = None) -> KnowledgeGraphSummary:
    repo_path = resolve_repo(source)
    repo_id = repo_id or derive_repo_id(source)
    summary = KnowledgeGraphSummary(repo_id=repo_id)

    per_file: list[tuple[str, str, FileGraph]] = []
    for file_path in _iter_source_files(repo_path):
        if _is_secret_file(file_path.name):
            continue
        text = _read_text(file_path)
        if text is None:
            continue

        rel_path = str(file_path.relative_to(repo_path))
        language = tslp.detect_language_from_path(rel_path) or "text"
        graph = extract_file_graph(text, language)
        per_file.append((rel_path, language, graph))

    create_all()
    with session_scope() as session:
        existing = session.execute(select(Repository).where(Repository.repo_id == repo_id)).scalar_one_or_none()
        if existing is not None:
            session.delete(existing)
            session.flush()

        repository = Repository(repo_id=repo_id, source=source)
        session.add(repository)
        session.flush()

        for rel_path, language, graph in per_file:
            file_row = File(repository_id=repository.id, file_path=rel_path, language=language)
            session.add(file_row)
            session.flush()
            summary.files += 1

            file_symbols = []
            for symbol in graph.symbols:
                symbol_row = Symbol(
                    file_id=file_row.id,
                    name=symbol.name,
                    kind=symbol.kind,
                    start_line=symbol.start_line,
                    end_line=symbol.end_line,
                )
                session.add(symbol_row)
                file_symbols.append(symbol_row)
                summary.symbols += 1
            session.flush()

            for imp in graph.imports:
                session.add(
                    Import(
                        file_id=file_row.id,
                        raw_source=imp.raw_source,
                        module_path=imp.module_path,
                        start_line=imp.start_line,
                    )
                )
                summary.imports += 1

            for call in graph.calls:
                match = next((s for s in file_symbols if s.name == call.callee_name), None)
                session.add(
                    Call(
                        file_id=file_row.id,
                        callee_name=call.callee_name,
                        callee_symbol_id=match.id if match else None,
                        start_line=call.start_line,
                    )
                )
                summary.calls += 1

            for endpoint in graph.endpoints:
                match = None
                if endpoint.handler_name:
                    match = next((s for s in file_symbols if s.name == endpoint.handler_name), None)
                session.add(
                    ApiEndpoint(
                        file_id=file_row.id,
                        method=endpoint.method,
                        path=endpoint.path,
                        handler_symbol_id=match.id if match else None,
                        framework_hint=endpoint.framework_hint,
                        start_line=endpoint.start_line,
                    )
                )
                summary.endpoints += 1

    return summary

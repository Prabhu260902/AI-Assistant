# Phase 3 — Repository Knowledge Graph

## What this phase adds

Given a repository already resolvable by Phase 2's `resolve_repo` (local path
or git URL), the backend now extracts a structured knowledge graph —
imports, symbols, a call graph, and API endpoints — and persists it to
Postgres. This is additive to Phase 2's vector index, not a replacement:
later phases can use Chroma for semantic search and Postgres for precise
structural questions ("what calls this function", "what endpoints exist").

- `backend/services/models.py` — SQLAlchemy models: `Repository`, `File`,
  `Symbol`, `Import`, `Call`, `ApiEndpoint`. Deliberately avoid
  Postgres-only column types so the same models work against an in-memory
  SQLite engine in tests.
- `backend/services/db.py` — `get_engine()`, `create_all()`, and a
  `session_scope()` context manager, reading `settings.database_url`.
- `backend/services/knowledge_graph.py` — the extraction + persistence
  logic (details below).
- `scripts/ingest_repo.py` — **extended** (not replaced) to call
  `build_knowledge_graph(...)` after the Phase 2 vector ingest, so one CLI
  invocation does both jobs and prints a combined summary.

## How extraction works

- **Imports & symbols**: `tree_sitter_language_pack.process(..., imports=True,
  symbols=True)` — language-generic, works for any of the ~300 languages the
  pack supports. Import module paths are best-effort parsed from the raw
  import statement text via a small regex per language family (Python:
  `from X import` / `import X`; JS/TS: the quoted string in the import).
- **Call graph & API endpoints**: scoped to **Python and JavaScript/
  TypeScript/TSX only**, via direct low-level tree-sitter queries
  (`tree_sitter.Query` + `QueryCursor`) — not covered by the generic
  `process()` API. Python endpoints are detected via `@router.get("/path")`
  -style decorators; JS/TS endpoints via `app.get("/path", handler)`-style
  calls. Both are filtered to a known HTTP-verb allowlist (`get/post/put/
  patch/delete/head/options`) to avoid false positives from unrelated
  decorators/calls (verified: `@app.on_event("startup")` and
  `logger.info("message")` are both correctly excluded).
- **Resolution**: call/endpoint-handler names are matched against known
  symbols **within the same file only** — a name-matching heuristic, not
  real import/scope resolution. An unresolved match (external library call,
  or a name defined elsewhere) is expected and left `NULL`.
- **Persistence**: `build_knowledge_graph` deletes any existing
  `Repository` row for the given `repo_id` (cascades to all its
  files/symbols/imports/calls/endpoints) and reinserts fresh — simpler than
  per-row upserts and equally correct/idempotent for a relational graph
  that can have files renamed or removed between runs.

## How to run it

```bash
docker compose -f docker/docker-compose.yml up -d postgres chroma
cd backend
uv run python ../scripts/ingest_repo.py /path/to/some/repo
```

Output:

```
repo_id:        hcp-crm
--- vector index ---
files_scanned:  38
files_indexed:  31
files_skipped:  7
chunks_indexed: 169
--- knowledge graph ---
files:          34
symbols:        54
imports:        110
calls:          566
endpoints:      13
```

To query the graph directly:

```python
from sqlalchemy import select
from services.db import session_scope
from services.models import ApiEndpoint

with session_scope() as session:
    for ep in session.execute(select(ApiEndpoint)).scalars().all():
        print(ep.method, ep.path)
```

Tests (fully offline — extraction tests need no DB at all; persistence
tests run against an in-memory SQLite engine, no Docker/Postgres needed):

```bash
cd backend
uv run pytest ../tests -v
```

## Real bugs found and fixed during verification

Running against `hcp-crm` again surfaced issues no unit test caught:

1. **Intermittent native segfault (exit 139) in `tree_sitter.Node.start_point`.**
   Accessing a captured `Node`'s `.start_point.row` — used to compute a
   call/endpoint's line number — crashed the Python process non-deterministically
   (same code, same file, sometimes crashed 3/3 runs, sometimes succeeded)
   when processing certain real files (e.g. `LogInteractionForm.jsx`). Root
   cause narrowed via `faulthandler` + repeated bisection to a specific,
   unstable code path in this `tree-sitter`/`tree-sitter-language-pack`
   version combination. Fixed by never touching `.start_point` — line
   numbers are now computed by counting newlines up to `node.start_byte`
   (`_line_number()` in `knowledge_graph.py`), the same proven-stable
   approach Phase 2's chunker already uses for `CodeChunk` boundaries.
   Verified stable across 10+ repeated runs after the fix; zero crashes.
2. **Corrupted `postgres_data` Docker volume.** Left over from Phase 1, the
   volume had no roles at all (not even the default `postgres` superuser) —
   Postgres never finished its first-run `initdb`. Since nothing had
   actually written real data to Postgres before this phase, the volume was
   removed and recreated cleanly with the user's confirmation.
3. **Host port 5432 collision.** A separate, non-Docker Postgres already
   running on the host was silently intercepting `localhost:5432`
   connections meant for the Docker container (`role "allease" does not
   exist` — the *other* server's error, not the container's). Fixed by
   remapping the Docker `postgres` service to host port **55432** (internal
   container-to-container traffic is unaffected — `backend`'s own
   `DATABASE_URL` still uses the internal port 5432). Updated in
   `docker/docker-compose.yml`, `config/.env.example`, and
   `backend/services/config.py`'s default.
4. **A stale `config/.env` leaked a real secret.** Left over from Phase 2's
   verification (not cleaned up afterward, unlike Phase 1's practice), it
   contained a real Groq API key copied from `hcp-crm`'s own leaked
   `.env` during that phase's investigation. It was gitignored and never
   committed, so it never left this machine — but it's been cleared. Lesson
   applied: always delete any `config/.env` created for verification at the
   end of the session, not just at the end of the phase it was created in.

## Known limitations

- Call graph and API endpoints are **Python + JS/TS/TSX only**; other
  languages still get imports/symbols (language-generic), just not
  calls/endpoints.
- The JS/TS endpoint query can't structurally distinguish a server route
  registration (`app.get(path, handler)`) from a client HTTP call
  (`axios.get(path)`) — both match the same `object.verb("path", arg)`
  shape. Confirmed in practice: `hcp-crm`'s `frontend/src/services/api.js`
  (an axios client) shows up in `api_endpoints` alongside the real FastAPI
  routes. Treat `framework_hint: express` results as "a route-shaped call,"
  not a guarantee it's a real server-side route.
- Call/endpoint-handler resolution is same-file name matching, not real
  import-aware symbol resolution — a function calling another function
  with the same name defined in a different file won't resolve correctly
  (documented trade-off from planning, not a bug).
- No `.gitignore`-aware filtering (same as Phase 2) — relies on the shared
  directory/secret-filename denylist in `services/ingest.py`.

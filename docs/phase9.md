# Phase 9 — Architecture Assistant

## What this phase adds

Given a natural-language question about a specific system flow, the backend
finds the most relevant starting point, traverses the real call graph from
there, renders a Mermaid flowchart from that grounded structure, and has
the LLM narrate it in prose. The diagram is built **programmatically** from
Postgres data — the LLM only describes a graph that already exists, so it
can't hallucinate a relationship that isn't really there. This is the first
phase to make Phase 3's `calls`/`api_endpoints` tables the primary data
source, not just a supporting signal.

- `backend/services/import_resolution.py` — small refactor: `fragments_for`
  (derive plausible import-name fragments for a file path) moved here from
  `impact_analysis.py`, which now has a second real consumer (this phase,
  resolving *forward* — "what does this file's import likely refer to" —
  rather than Phase 5's *reverse* "who imports this file"). No behavior
  change to Phase 5.
- `backend/services/architecture_graph.py`:
  - `find_starting_point(repo_id, file_path, start_line, end_line)`:
    resolves a hybrid-search hit's line **range** to the `Symbol` it falls
    in, via range overlap; labels it `kind="endpoint"` if it's also an
    `ApiEndpoint.handler_symbol_id`.
  - `build_flow_graph(repo_id, start_symbol_id, start_node, max_depth=3,
    max_nodes=25)`: BFS from the start symbol. A same-file call resolves
    via `Call.callee_symbol_id`; an unresolved call first tries a
    cross-file hop (`import_resolution.fragments_for` matched against the
    caller's `Import` rows); anything still unresolved becomes a `kind=
    "external"` leaf node labeled with the raw call text. Bounded by
    `max_depth`/`max_nodes`.
- `backend/services/mermaid.py` — `render_flow_graph(graph)`: plain
  `flowchart TD` syntax, quote-sanitized labels, distinct shapes for
  endpoint (`[[...]]`), function (`[...]`), and external (`(...)`) nodes.
- `backend/prompts/architecture.py` — describes the already-built graph as
  a bulleted list of nodes/edges and asks for prose only — never asked for
  Mermaid or JSON.
- `backend/agents/architecture.py` — `build_graph_node` (hybrid search →
  starting point → traversal → Mermaid, all grounded, no LLM) and
  `explain_node` (LLM narrates the graph, plain text).
- `backend/graphs/architecture.py` — `build_graph → explain → END`;
  `run_architecture_explanation(repo_id, query, top_k=5)`.
- `backend/main.py` — `POST /architecture` → `{repo_id, query, top_k?}` →
  `{explanation, mermaid_diagram, nodes, edges}` — grounded data included
  alongside the narrative, same transparency pattern as Phase 5/8's findings.

## How to run it

```bash
docker compose -f docker/docker-compose.yml up -d postgres chroma
# repo must be ingested into both — see docs/phase2.md and docs/phase3.md

cd backend
uv run uvicorn main:app --reload
```

```bash
curl -X POST localhost:8000/architecture \
  -H "Content-Type: application/json" \
  -d '{"repo_id": "hcp-crm", "query": "How does creating an HCP work?", "top_k": 8}'
```

Requires `GROQ_API_KEY` for the explanation; the graph/diagram themselves
need no LLM call. Tests (fully offline):

```bash
cd backend
uv run pytest ../tests -v
```

## Two real bugs found during verification against `hcp-crm` — neither caught by the offline tests

**1. `find_starting_point` used exact start-line containment, not range overlap.**
A retrieved chunk `[129, 170]` and the real symbol it should have matched,
`get_hcp_history` `[130, 168]`, clearly overlap — but the original query
(`symbol.start_line <= chunk_start_line`) rejected it outright, since
`130 <= 129` is false. Every offline test happened to use chunks whose
start line fell cleanly inside the target symbol, so this never surfaced
until a real hybrid-search hit landed one line early. Fixed by matching on
range overlap (`symbol.start_line <= end_line AND symbol.end_line >=
start_line`) instead, with a regression test reproducing the exact
boundary shape.

**2. `Call.caller_symbol_id` — a Phase 3 column — was never actually
populated.** Confirmed directly: 0 of 566 real `Call` rows in `hcp-crm`
have it set. Phase 3's extraction only ever determined the *callee* side
of a call, never which symbol contains it. This meant Phase 9's core
traversal (`WHERE caller_symbol_id = ?`) always returned zero results
beyond the starting node — every real query produced a lone, edge-less
diagram, which looked at first like a retrieval-ranking problem but wasn't.
**Fixed entirely within this phase**, per the user's explicit direction not
to touch Phase 3's code: `_calls_within_symbol` now recomputes "which
calls belong to this symbol" at query time, from `Call.start_line` falling
inside the symbol's own line range — the same technique as fix #1, just
applied to calls instead of hybrid-search hits. No Phase 3 file changed, no
re-ingestion needed, works retroactively on already-ingested data. A
regression test seeds a fixture with `caller_symbol_id` left `None`
everywhere (matching real data) to lock this in.

After both fixes, a real query against `hcp-crm` produced an 18-node graph
for `create_hcp`, including a **confirmed cross-file hop** into the `HCP`
class in `backend/models/db_models.py`, with an accurate LLM explanation
grounded in exactly that structure.

## Known limitations

- `_calls_within_symbol` doesn't exclude calls that are actually inside a
  *nested* symbol defined within the current one's range (e.g. a closure) —
  they'd be attributed to the outer symbol too. Disclosed simplification,
  not full scope analysis.
- Cross-file hop resolution is the same fragment-matching heuristic as
  Phase 5 — not exact import resolution, and only hops when exactly one
  candidate file matches.
- The *first hit that resolves* isn't always the most relevant one for
  ambiguous queries — confirmed in practice: "How does creating an HCP
  work?" repeatedly resolved to `search_hcps` rather than `create_hcp`
  because it ranked/resolved first. The LLM correctly avoided inventing an
  answer it couldn't support ("this flow does not describe creating an
  HCP") rather than guessing — same honest-degradation behavior as prior
  phases, but a more specific query (naming the function or endpoint
  directly) gets a much better result, same lesson as Phase 4/5.

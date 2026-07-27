# Phase 5 — Feature Planner Agent

## What this phase adds

Given a feature description, the backend now produces an implementation
plan grounded in the actual repo: real affected files (not hallucinated),
computed blast-radius signals, and risks that combine hard data with LLM
judgment. This is the payoff for having built both a vector index (Phase 2)
and a knowledge graph (Phase 3) — Phase 5 is the first thing to actually
combine them, on top of Phase 4's retrieval plumbing.

- `backend/services/impact_analysis.py` — `find_affected_modules(repo_id,
  direct_file_paths)`. Phase 3's `Call.callee_symbol_id` only ever resolves
  same-file calls, so it can't answer "who depends on file X" — this uses
  the `imports` table instead: for each directly-relevant file, derive name
  fragments (e.g. `hcps`, `routers.hcps` for `backend/routers/hcps.py`) and
  search other files' stored `Import.module_path`/`raw_source` for them.
  A substring heuristic, not exact import resolution — disclosed, same
  spirit as Phase 3's own resolution logic. Also computes `fan_in` (how
  many files reference this one) and `has_api_endpoint` (join
  `ApiEndpoint`) per affected module.
- `backend/prompts/feature_planner.py` — includes the feature description,
  retrieved code context (same labeled-block format as Phase 4), and the
  affected-modules list with their signals; asks the model for a plan
  followed by a line containing exactly `RISKS:` and `- `-prefixed bullets —
  a plain-text delimiter, deliberately avoiding a JSON-parsing dependency.
- `backend/agents/feature_planner.py` — three nodes: `retrieve_node`
  (reuses Phase 4's `hybrid_search.search_repo` unchanged),
  `analyze_impact_node` (calls `impact_analysis.find_affected_modules` on
  the unique files retrieval found), `generate_node` (builds the prompt,
  calls the LLM, splits the response on `RISKS:`, and **prepends** computed
  risk strings — high fan-in ≥3, or exposes an API endpoint — ahead of the
  LLM's own risk bullets).
- `backend/graphs/feature_planner.py` — `retrieve → analyze_impact →
  generate`, mirroring Phase 4's graph module. `run_feature_plan(repo_id,
  feature_description, top_k=5)`.
- `backend/main.py` — new `POST /plan`: `{repo_id, feature_description,
  top_k?}` → `{plan, affected_modules: [{file_path, reason, fan_in,
  has_api_endpoint}], risks: [str]}`.

## How to run it

```bash
docker compose -f docker/docker-compose.yml up -d postgres chroma
# repo must be ingested into BOTH stores — see docs/phase2.md if not:
# cd backend && uv run python ../scripts/ingest_repo.py /path/to/repo

cd backend
uv run uvicorn main:app --reload
```

```bash
curl -X POST localhost:8000/plan \
  -H "Content-Type: application/json" \
  -d '{"repo_id": "hcp-crm", "feature_description": "Add a field to track HCP specialty and show it in search results", "top_k": 5}'
```

Or directly: `from graphs.feature_planner import run_feature_plan`.
Requires `GROQ_API_KEY` for the plan/risk text; impact analysis itself
works without it.

Tests (fully offline, same DI patterns as Phases 2–4):

```bash
cd backend
uv run pytest ../tests -v
```

## Verified against `hcp-crm`

Real query: *"Add a field to track HCP specialty and show it in search
results."* Result:

- **Plan** correctly named real files/functions: `backend/models/db_models.py`,
  `backend/models/schemas.py`'s `HCPCreate`, `backend/routers/hcps.py`'s
  `create_hcp` and `search_hcps`, `frontend/src/components/HcpSearch.jsx`.
- **Affected modules** correctly flagged `backend/routers/hcps.py` as
  directly relevant with `fan_in=3, has_api_endpoint=true`, and correctly
  expanded to real dependents (`backend/main.py`, `backend/agent/tools.py`
  and `backend/agent/graph.py` via `backend/agent/prompts.py`).
- **Risks** mixed grounded computed flags ("High fan-in: 3 other file(s)
  import backend/routers/hcps.py", "Public API surface... exposes an API
  endpoint") with LLM-authored judgment (data validation, backwards
  compatibility, query performance).

Confirmed working both via direct `run_feature_plan(...)` call and through
the live `POST /plan` HTTP endpoint.

## Real issue found during verification

A **leftover backend process from Phase 4's verification session** was
still holding port 8000, so this phase's `uvicorn` silently failed to bind
and the first `curl` returned `404 Not Found` — not a code bug, but a
process-hygiene gap: killing a background server with `kill %1` doesn't
reliably work across separate tool-call boundaries in this environment, so
the Phase 4 server was never actually stopped. Fixed by killing it by PID
directly and doing the same at the end of this phase's verification too.
Lesson for future phases: verify a port is actually free (`lsof`) before
trusting a server started in the same session is the one responding.

## Known limitations

- Reverse-import expansion is a fragment/substring heuristic over already
  best-effort-parsed import text — it can produce plausible-but-imprecise
  matches (observed: a frontend `.jsx` file was flagged as "importing"
  a backend `.py` file because both shared the fragment `hcps`, when what's
  actually true is the frontend file calls an API client function related
  to HCPs, not a literal cross-language import). Treat "affected modules"
  beyond the direct hits as a hint to check, not a certainty.
- Same-repo only; no cross-repo impact analysis.
- Computed risk flags are threshold-based (`fan_in >= 3`, any API endpoint)
  — not tuned per repo size; a very small or very large repo may want
  different thresholds.

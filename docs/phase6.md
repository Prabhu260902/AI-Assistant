# Phase 6 — Ticket Generator

## What this phase adds

Given a feature description, the backend now runs the full pipeline
end-to-end: retrieve relevant code → analyze impact → plan (Phase 5) →
break the plan into epics, stories, and tasks with acceptance criteria and
test cases. This is the first phase whose entire output is structured JSON
rather than free text, and the first to compose an entire prior phase
(Phase 5) as a single reused node rather than re-implementing any of its
logic — the shape Phase 10's eventual router is meant to build on.

- `backend/services/llm.py` — small, backward-compatible change:
  `LLMProvider.complete()` gained an optional `json_mode: bool = False`
  parameter; `GroqProvider` sets Groq's `response_format: {"type":
  "json_object"}` when true. Existing Phase 4/5 callers are unaffected
  (parameter defaults to `False`, behavior unchanged) — verified by the
  existing test suite still passing untouched.
- `backend/state/ticket_state.py` — `Task`, `Story`, `Epic` as **Pydantic**
  models (not dataclasses, unlike `AffectedModule`) because this phase's
  output is validated directly from the LLM's JSON response via
  `TicketBreakdown.model_validate_json(...)`, and the same models double as
  the FastAPI response shape with no dataclass→dict conversion step.
- `backend/prompts/ticket_generator.py` — includes the Phase 5 plan,
  affected modules, and risks as grounding context; shows the exact target
  JSON shape as an example (paired with `json_mode=True`, not relied on
  alone — JSON mode constrains syntax, not the schema).
- `backend/agents/ticket_generator.py`:
  - `plan_node`: calls Phase 5's `run_feature_plan(...)` unchanged and
    copies `plan`/`affected_modules`/`risks` into this graph's state.
  - `generate_tickets_node`: builds the prompt, calls the LLM with
    `json_mode=True`, strips markdown code fences (a common LLM quirk even
    in JSON mode), and validates with `TicketBreakdown.model_validate_json`.
    On `ValidationError` (bad JSON *or* wrong shape — Pydantic v2 raises
    the same exception for both), falls back to a single epic wrapping the
    raw response text, so nothing is silently lost.
- `backend/graphs/ticket_generator.py` — `plan → generate_tickets → END`;
  `run_generate_tickets(repo_id, feature_description, top_k=5)`.
- `backend/main.py` — new `POST /tickets`: `{repo_id, feature_description,
  top_k?}` → `{plan, affected_modules, risks, epics}`.

No new Postgres tables — tickets are returned in the response only, same as
Phases 4–5.

## How to run it

```bash
docker compose -f docker/docker-compose.yml up -d postgres chroma
# repo must be ingested into BOTH stores — see docs/phase2.md if not

cd backend
uv run uvicorn main:app --reload
```

```bash
curl -X POST localhost:8000/tickets \
  -H "Content-Type: application/json" \
  -d '{"repo_id": "hcp-crm", "feature_description": "Add a field to track HCP specialty and show it in search results", "top_k": 5}'
```

Or directly: `from graphs.ticket_generator import run_generate_tickets`.
Requires `GROQ_API_KEY`.

Tests (fully offline):

```bash
cd backend
uv run pytest ../tests -v
```

## Verified against `hcp-crm`

Same real query as Phase 5 ("Add a field to track HCP specialty and show it
in search results"), run through the full pipeline. **JSON mode produced
valid, well-structured output on the first call, no fallback needed** — 1
epic ("HCP Specialty Feature Implementation") containing 3 stories (model/
schema update, search functionality, HCP creation/seed data), each with
concrete acceptance criteria, test cases, and 2 tasks apiece — all grounded
in the exact real files Phase 5 identified (`backend/models/db_models.py`,
`backend/models/schemas.py`, `backend/routers/hcps.py`'s `search_hcps` and
`create_hcp`, `backend/seed.py`, `frontend/src/components/HcpSearch.jsx`).
Confirmed working both via direct `run_generate_tickets(...)` and through
the live `POST /tickets` HTTP endpoint, full response verified end-to-end
including nested epic → story → task JSON serialization.

## Notes from verification

- Repeated the Phase 5 lesson: checked `lsof -nP -iTCP:8000 -sTCP:LISTEN`
  before starting the server this time, confirmed clean, and killed the
  server by PID (not `kill %1`, which still doesn't reliably work across
  separate tool-call boundaries in this environment) once done.
- Docker volumes had reset again since Phase 5 (fresh `postgres:16-alpine`
  image pull) — re-ran `scripts/ingest_repo.py` before verifying; this
  appears to happen between sessions in this environment and is worth
  expecting at the start of each future phase's verification rather than
  assuming prior data persisted.

## Known limitations

- No retry loop: if `json_mode=True` still produces invalid/malformed JSON
  (schema mismatch, not just bad syntax), the fallback is a single
  informational epic, not a retried LLM call. Acceptable for this phase's
  scope; a future phase could add a retry-with-error-feedback loop if this
  proves to happen often in practice (it did not in real testing here).
- Ticket quality is only as good as Phase 5's plan/affected-modules output —
  this phase adds no new grounding beyond what it inherits.

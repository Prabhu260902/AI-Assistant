# Phase 10 — Engineering Copilot (Intent Router)

## What this phase adds

The final phase: one endpoint, `POST /copilot`, that takes a free-form
natural-language message plus a `repo_id` and figures out which of the
six existing agents actually answers it, then dispatches to that agent's
own `run_*` function and returns the result — so a caller doesn't need to
know that `/search`, `/plan`, `/tickets`, `/implement`, `/review`, and
`/architecture` exist separately. This is the composition pattern
`docs/phase6.md` named as the intended shape for this phase: structured
JSON classification (the same `json_mode` mechanism every JSON-output
agent has used since Phase 6) dispatching to a prior phase's `run_*`
function reused as-is, applied one level up across all six agents instead
of one.

- `backend/state/router_state.py` — `RouterState` TypedDict
  (`repo_id, message, top_k, intent, base_ref, head_ref, result: dict`) and
  `RouterClassification` (Pydantic: `intent: Literal[...]`,
  `base_ref: str | None`, `head_ref: str | None`).
- `backend/prompts/router.py` — `build_router_prompt(message)`: spells out
  the distinguishing criteria between the six intents (particularly the
  two genuinely ambiguous pairs — architecture vs. search, and
  plan vs. tickets vs. implement) and instructs an explicit fallback to
  `"search"` for anything that doesn't clearly match the other five.
- `backend/agents/router.py`:
  - `classify_node`: one `json_mode=True` LLM call, validated against
    `RouterClassification`, falling back to `{"intent": "search"}` on a
    `ValidationError` — same graceful-degradation convention as
    `pr_review.py`/`ticket_generator.py`.
  - `dispatch_node`: calls the matching `run_*` function directly
    (`run_code_search`, `run_feature_plan`, `run_generate_tickets`,
    `run_implementation`, `run_pr_review`, `run_architecture_explanation`)
    — the same "call a prior graph's `run_*` function from a node"
    composition already used by `implementation.py`/`ticket_generator.py`
    for `run_feature_plan`, just generalized across all six. For
    `"review"`, defaults `base_ref`/`head_ref` to `"main"`/`"HEAD"` when
    the LLM didn't extract explicit refs from the message, and lets
    `GitDiffError` propagate uncaught — a bad ref is a real error to
    surface, same as `pr_review.py`'s own node.
- `backend/graphs/router.py` — `classify → dispatch → END`;
  `run_copilot(repo_id, message, top_k=5) -> RouterState`.
- `backend/main.py` — `POST /copilot` → `{repo_id, message, top_k?}` →
  `{intent, result}`. `result` is the dispatched agent's own state,
  passed through a new `_to_jsonable()` helper that recursively converts
  dataclasses (`FlowGraph`, `SearchResult`, `AffectedModule`) and Pydantic
  models (`ProposedChange`, `Finding`, `Epic`) to plain JSON — needed
  because `/copilot` funnels all six differently-shaped results through
  one generic response instead of six separate typed ones.
- **Deliberately excluded**: `/implement/apply` (writes files to disk) is
  never a router target. Applying changes stays a separate, explicit,
  human-reviewed call — the router only ever reaches read-only/dry-run
  agents.
- **Bonus fix surfaced by verification, not originally in the plan**:
  `backend/services/llm.py`'s `GroqProvider` now accepts
  `fallback_models: list[str]` and retries the next model in the list on
  a 429, only when it's a rate/quota error and another model is left to
  try — any other error (auth, bad request) propagates immediately since
  switching models wouldn't fix it. `services/config.py` adds
  `groq_fallback_models`, defaulting to
  `["llama-3.1-8b-instant", "openai/gpt-oss-20b"]`. See below for why this
  was needed.

## How to run it

```bash
docker compose -f docker/docker-compose.yml up -d postgres chroma
cd backend
uv run uvicorn main:app --reload
```

```bash
curl -X POST localhost:8000/copilot \
  -H "Content-Type: application/json" \
  -d '{"repo_id": "hcp-crm", "message": "How does creating an HCP work?"}'
```

Tests (fully offline):

```bash
cd backend
uv run pytest ../tests -v
```

## Real bugs and constraints found during verification against `hcp-crm`

**1. Groq's free tier has a hard 100,000 Tokens-Per-Day cap per model —
and this project's cumulative verification traffic (Phases 1–10, all in
one day) hit it mid-session.** A direct probe returned:
```
Rate limit reached for model `llama-3.3-70b-versatile` ... tokens per day
(TPD): Limit 100000, Used 97915, Requested 2223. Please try again in 1m59s.
```
This wasn't a transient per-minute burst — it kept recurring across
multiple retries with growing backoff, including on the router's own
single-call `classify_node`, not just the multi-call `implement` intent.
**Fixed** by adding model fallback to `GroqProvider` (details above).
Confirmed each Groq model has its **own separate rate/quota bucket** — a
direct probe of `llama-3.1-8b-instant` succeeded immediately (`200 OK`)
while `llama-3.3-70b-versatile` was still 429'ing, so falling back
actually unblocks a request rather than hitting the same wall again. This
also caught a second, smaller issue: the first fallback model chosen
(`llama3-70b-8192`, a plausible-looking Groq model name) turned out to be
**decommissioned** (`400 Bad Request`, not `429`) — confirmed via a live
`GET /openai/v1/models` probe against Groq's own catalog, and the
fallback list was corrected to `llama-3.1-8b-instant` and
`openai/gpt-oss-20b`, both verified live. The `complete()` retry loop
correctly distinguishes the two cases: it only falls through to the next
model on `429`, and re-raises immediately on anything else (like the
`400` from the decommissioned model) — a different model can't fix a
malformed request or bad auth, so there's no reason to keep trying.

**2. LLM-based ref extraction can mangle unusual branch names.** Asking
the router to review "the diff between main and
`allease/phase7-verification`" (a real leftover branch from Phase 7's own
verification) caused the classifier to transcribe the branch name as
`allelase/phase7-verification` — then `alsease/phase7-verification` on a
retry with the identical prompt. Both are near-miss typos of "allease"
(this project's own name), reproducible across attempts. This surfaced
the router's design correctly: the malformed ref was rejected by git with
a clear message, `GitDiffError` propagated as designed, and `/copilot`
correctly returned `400` rather than crashing or silently guessing.
Disclosed as a known limitation below rather than "fixed," since there's
no reliable way to force an LLM to transcribe an arbitrary string
perfectly — see Known Limitations.

**3. No router-logic bugs.** Every one of the six intents classified and
dispatched correctly on the first real query that reached a healthy
model, including the ambiguous fallback case ("hi, what can you help me
with?" → `"search"`, matching a real answer grounded in the repo) and the
review path's ref defaulting (a message with no explicit refs correctly
defaulted to `main`/`HEAD` and reported "No changes found" — verified
directly against `git diff main...HEAD`, which was genuinely empty).

## Known limitations

- **Ref extraction from free text is not reliable for unusual branch
  names.** The router asks the LLM to pull `base_ref`/`head_ref` out of
  the message rather than requiring structured input, and a smaller/
  fallback model under load can transcribe an exact string incorrectly
  (see bug #2 above). Reviewing a diff by exact ref name is safer done via
  the dedicated `/review` endpoint directly when the ref name matters.
- **Fallback models trade quality for availability.** When the primary
  `llama-3.3-70b-versatile` is rate/quota-limited, responses come from a
  smaller model (`llama-3.1-8b-instant` or `openai/gpt-oss-20b`).
  Observed directly: an `"implement"` request for HCP-list pagination,
  served entirely by a fallback model once the primary was exhausted,
  proposed changes to `README.md` and `backend/agent/tools.py` alongside
  the actually-relevant router file — plausible-looking but less
  precisely scoped than the 70b model's output seen in earlier phases.
  The fallback exists to keep the copilot answering rather than hard-
  failing; it does not guarantee equivalent output quality.
- **The classifier's boundary between architecture/search and between
  plan/tickets/implement is prompt-based, not guaranteed.** The system
  instructions spell out the distinguishing criteria explicitly, but a
  genuinely ambiguous message can still land on the "wrong" specific
  intent rather than the fallback. This is the same class of limitation
  already disclosed in Phase 9 (retrieval/resolution picking a plausible
  but non-primary starting point) — a more specific message gets a more
  reliable classification.
- **`/implement/apply` is intentionally unreachable from the router.** Any
  copilot response that proposes code changes still requires a separate,
  explicit call to apply them — this is a deliberate scope boundary, not
  a gap to close in a future phase.

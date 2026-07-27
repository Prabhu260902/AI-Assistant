# Phase 8 — PR Review Agent

## What this phase adds

The backend can now review a diff between two git refs in an ingested repo
for correctness, security, performance, and test coverage — a natural next
step after Phase 7 (review the branch it just created before deciding to
commit/merge). Findings combine two **grounded, non-LLM** signals with the
LLM's own judgment, same "ground what we can, let the LLM add the rest"
philosophy as Phase 5's risk flags.

- `backend/services/repo_registry.py` — small refactor: `get_repo_source`
  moved here from `agents/implementation.py` now that a second real
  consumer (this phase) needs it. No behavior change; `agents/implementation.py`
  and `main.py` just import from the new shared location.
- `backend/services/git_diff.py` — `get_diff`/`get_changed_files(repo_source,
  base_ref, head_ref)`, both `git diff base_ref...head_ref` (three-dot —
  same range semantics GitHub uses for a PR diff) via `subprocess`, same
  pattern as `code_apply.py`/`repo_loader.py`. Raises `GitDiffError` with a
  clear message for a bad ref, deliberately left to propagate rather than
  swallowed — a missing ref is a real error the caller needs to know about.
- `backend/services/review_signals.py` — the two grounded signals:
  - `scan_for_secrets(diff_text)`: regex over added (`+`) lines for
    secret-shaped patterns (key/secret/token/password assignments, AWS
    access-key shape, bearer-token shape) — same spirit as Phase 2's
    filename-based secret denylist, applied to line content instead.
  - `check_test_coverage(repo_path, changed_files)`: flags a changed file
    if no plausible test file exists in the same directory or a sibling
    `tests/`/`test/`/`__tests__` dir, checking common naming conventions
    (`test_x.py`, `x_test.py`, `x.test.js`, `x.spec.ts`, etc.).
- `backend/state/review_state.py` — `Finding` (Pydantic:
  `category, severity, file_path, line, description`), `ReviewBreakdown`
  (`summary, findings`, validated from the LLM's JSON), `ReviewState`.
- `backend/prompts/pr_review.py` — gives the model the diff and the
  already-identified grounded findings (so it doesn't waste output
  repeating them) and asks for additional correctness/security/performance
  findings as JSON.
- `backend/agents/pr_review.py`:
  - `diff_node`: resolves the repo path, computes the diff + changed
    files, runs both grounded checks.
  - `generate_review_node`: calls the LLM with `json_mode=True`, validates
    the response, merges grounded findings ahead of the LLM's own findings.
    On a malformed response, falls back to the grounded findings alone
    rather than losing everything (same graceful-degradation pattern as
    Phase 6).
- `backend/graphs/pr_review.py` — `diff → generate_review → END`;
  `run_pr_review(repo_id, base_ref, head_ref)`.
- `backend/main.py` — `POST /review` → `{repo_id, base_ref, head_ref}` →
  `{summary, findings}`. Returns `400` for a bad ref.

## How to run it

```bash
docker compose -f docker/docker-compose.yml up -d postgres  # Chroma not needed — no vector search here
# repo must be ingested into Postgres (Phase 3) — see docs/phase3.md

cd backend
uv run uvicorn main:app --reload
```

```bash
curl -X POST localhost:8000/review \
  -H "Content-Type: application/json" \
  -d '{"repo_id": "my-repo", "base_ref": "main", "head_ref": "feature/x"}'
```

Requires `GROQ_API_KEY`. Tests (fully offline — `test_git_diff.py` and
`test_pr_review_agent.py` create real throwaway git repos via subprocess,
no mocking needed for git itself):

```bash
cd backend
uv run pytest ../tests -v
```

## Verified with a real Groq call — plus a real discrepancy caught along the way

The original plan was to review `hcp-crm`'s real `main` vs.
`allease/phase7-verification` diff (Phase 7's actual changes). Checking
directly with git before running anything revealed the two refs were
**identical commits** — the changes the user believed were committed were
actually sitting in `git stash` instead (`stash@{0}: WIP on
allease/phase7-verification...`), never landed on the branch. The tool's
"No changes found between the given refs" response was **correct**, not a
bug — it exposed the discrepancy rather than papering over it. Per the
user's direction, `hcp-crm` was left untouched, and a small throwaway repo
was used instead to verify a real LLM call end-to-end.

Real review of a demo diff (a hardcoded Stripe key + an unguarded
`delete_all_users()` function): both grounded signals fired correctly
(the secret, and the missing test file), and the LLM's own findings went
beyond what the heuristics could catch — it independently flagged that
`delete_all_users()` has **no authorization check**, a real and serious
issue neither grounded signal was designed to catch. Confirmed both via
direct `run_pr_review(...)` and the live `POST /review` endpoint, full
response verified including nested finding serialization.

## Known limitations

- The test-coverage heuristic only checks the same directory and a sibling
  `tests/`/`test/`/`__tests__` dir — a repo-root `tests/` mirroring the
  source tree elsewhere (like this very project's own `tests/backend/`
  layout) won't be found by this heuristic. Deliberately scoped this way
  per the plan rather than guessing more broadly and risking noise.
- Secret scanning is regex-based and pattern-limited (three shapes) — not
  a substitute for a real secret-scanning tool, just a cheap grounded
  signal alongside the LLM's own judgment.
- No handling for huge diffs — a very large diff is sent to the LLM as-is,
  with no chunking or size limit.

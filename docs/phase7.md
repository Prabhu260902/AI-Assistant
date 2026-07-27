# Phase 7 — Implementation Assistant

## What this phase adds

The backend can now go all the way from a feature description to actual
code changes on disk — the first phase that writes to a real repository.
Safety is the whole design: a strict two-step API separates proposing
changes (read-only) from applying them (writes, gated), and applying
always happens on an isolated git branch that's never auto-committed.

- `backend/services/code_apply.py` — `apply_changes(repo_source, changes,
  branch_name)`: rejects non-local or non-git `repo_source`; rejects a
  dirty working tree (`git status --porcelain`); rejects an already-existing
  branch name; rejects any `file_path` that resolves outside the repo
  (path traversal guard); creates the branch (`git checkout -b`); writes
  each file (must already exist — this phase only edits, never creates
  files); **never commits**. All git calls go through `subprocess` with an
  argument list (no `shell=True`), same pattern as Phase 2's
  `repo_loader.py`.
- `backend/state/implementation_state.py` — `ProposedChange` (Pydantic:
  `file_path, diff, new_content`); `ImplementationState` (TypedDict,
  shares `plan`/`risks`/`context_results` field names with Phase 5's
  `FeaturePlanState` since `plan_node` feeds directly from it).
- `backend/prompts/implementation.py` — gives the model the plan and a
  single file's full current content, asks for the complete new content of
  *that file only*, no fences, no commentary, no unrelated changes.
- `backend/agents/implementation.py`:
  - `plan_node`: calls Phase 5's `run_feature_plan(...)` unchanged (same
    composition pattern as Phase 6), keeping `context_results` — the
    direct hybrid-search hits, which become the regeneration scope.
  - `generate_code_node`: resolves the repo's real local path via
    `Repository.source` (Postgres); for each unique file in
    `context_results`, reads it, regenerates it, computes a unified diff
    (`difflib`, stdlib), and skips it if unchanged or missing from disk.
- `backend/graphs/implementation.py` — `plan → generate_code → END`;
  `run_implementation(repo_id, feature_description, top_k=5)`.
- `backend/main.py`:
  - `POST /implement` — dry run. Retrieves, plans, generates proposed
    diffs. **Writes nothing.**
  - `POST /implement/apply` — the caller resubmits the exact file contents
    they want written (nothing is persisted server-side between the two
    calls — resubmission is itself part of the confirmation). Returns
    `409` on any safety-check rejection, `404` for an unknown `repo_id`.

## How to run it

```bash
docker compose -f docker/docker-compose.yml up -d postgres chroma
# repo must be ingested into both — see docs/phase2.md

cd backend
uv run uvicorn main:app --reload
```

```bash
# 1. Dry run — review the diffs before doing anything else
curl -X POST localhost:8000/implement \
  -H "Content-Type: application/json" \
  -d '{"repo_id": "hcp-crm", "feature_description": "...", "top_k": 5}'

# 2. Only if you approve, apply — resubmit the exact file_path/new_content pairs
curl -X POST localhost:8000/implement/apply \
  -H "Content-Type: application/json" \
  -d '{"repo_id": "hcp-crm", "changes": [...], "branch_name": "allease/my-feature"}'
```

Requires a **clean working tree** and a **local** (not URL) `repo_id`
source. Tests (fully offline — `test_code_apply.py` creates real throwaway
git repos via subprocess, no mocking needed for git itself):

```bash
cd backend
uv run pytest ../tests -v
```

## Verified against `hcp-crm` — full real flow, not just offline tests

1. **Dry run** with a real Groq call proposed changes to 5 files
   (`README.md`, `backend/agent/prompts.py`, `backend/routers/hcps.py`,
   `backend/seed.py`, `frontend/src/components/HcpSearch.jsx`) with a
   coherent plan and 8 risks (3 computed, 5 LLM-authored).
2. **Real apply**, with the user's explicit go-ahead at that specific
   moment (not just the earlier design approval) and after the user
   committed a pre-existing unrelated uncommitted change so the working
   tree was clean: created `allease/phase7-verification`, wrote all 5
   files as uncommitted changes, made **zero commits**.
3. Confirmed directly in the real repo: `git branch --show-current` →
   the new branch; `git log main --oneline` → still a single commit,
   completely untouched; `git status --porcelain` → exactly the 5 expected
   modified files.
4. Confirmed the dry-run endpoint over live HTTP too, reflecting the
   *current* on-disk state correctly (a second call after the apply showed
   fewer proposed changes, because it was now diffing against the
   already-updated files, not the pre-apply originals — correct behavior,
   not a bug).

## Real bug found and fixed during verification

The first dry-run's diff for `README.md` was corrupted: every one of the
file's own ` ```bash ` code-fence markers throughout the document had been
stripped, not just a wrapping fence around the LLM's whole response. Root
cause: the fence-stripping regex (`^```[a-zA-Z]*\s*|\s*```$` with
`MULTILINE`) matched **every** line starting or ending with `` ``` ``
anywhere in the file, not just a single pair wrapping the entire response —
fine for a code file with no internal fences, silently destructive for a
markdown file that legitimately contains its own embedded code blocks.
Fixed by checking only whether the *first and last line of the whole
trimmed response* are fence markers, leaving everything in between —
including any real internal `` ``` `` sequences — untouched. Added a
regression test (`test_generate_code_preserves_internal_code_fences`)
seeded with exactly this shape of content.

## Known limitations (some observed directly during verification, not just theoretical)

- **Full-file regeneration can introduce unrelated regressions.** Observed
  directly: on one run, the model changed `hcp_in.model_dump()` to the
  deprecated `hcp_in.dict()` in `backend/routers/hcps.py` — unrelated to
  the requested feature and not something the prompt asked for. This is an
  inherent tradeoff of the full-file-regeneration approach (chosen over
  LLM-authored diffs specifically for reliable *application*, not
  necessarily minimal *edits*) — not something this phase attempts to
  eliminate. Always review diffs before applying.
- Regeneration is scoped to Phase 5's *direct* hybrid-search hits only —
  reverse-import dependents are shown as risk context but never
  regenerated, so a feature that truly needs changes in a dependent file
  won't get them automatically.
- Only edits existing files; cannot create new files.
- Local-path repos only — a `Repository.source` that's a git URL isn't a
  valid apply target.
- No commit step by design — a human must `git commit` (or discard) the
  applied changes themselves.

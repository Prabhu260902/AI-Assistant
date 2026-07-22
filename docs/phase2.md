# Phase 2 — Repository Understanding

## What this phase adds

Given an arbitrary repository (local path or git URL), the backend can now:
clone/read it, parse its files with Tree-sitter, chunk them along syntax
boundaries, embed the chunks, and index them into Chroma — so later phases
(starting with the Phase 4 Code Search Agent) have something to query.
Nothing here is AllEase/hcp-crm-specific; it's proven against a real repo
(`hcp-crm`) but works identically against any repo shape or language.

- `backend/services/repo_loader.py` — `resolve_repo(source)`: if `source` is
  an existing local path, reads it in place; if it looks like a git URL,
  shallow-clones it (`git clone --depth 1`, via the system `git` binary — no
  new dependency) into a temp dir. `derive_repo_id(source)` turns a path/URL
  into a sanitized id used as the Chroma collection name.
- `backend/services/chunker.py` — `chunk_text(text, path)`: detects the
  file's language via `tree_sitter_language_pack.detect_language_from_path`
  and chunks it with the library's `process()` API, which splits along
  syntax boundaries for ~300 languages. Files with no detected grammar (or
  where parsing fails) fall back to fixed 60-line windows — every file still
  gets indexed either way. Chunk boundaries are **byte-precise**, not
  line-range-precise: `start_line`/`end_line` are derived from
  `start_byte`/`end_byte` for accurate citations, but multiple small chunks
  can legitimately land on the same line (e.g. `export default function
  Foo()` split into two chunks on one physical line) — see "Bugs found and
  fixed" below.
- `backend/services/ingest.py` — `ingest_repository(source, repo_id=None)`:
  walks the repo (skipping a denylist of directories and known secret
  filenames — see below), chunks each file, and upserts everything into one
  Chroma collection per repo via `index_chunks(collection, chunks)`. Chunk
  IDs are `f"{repo_id}:{file_path}:{start_byte}-{end_byte}"`, so re-running
  ingestion **upserts** (idempotent) rather than duplicating.
- `scripts/ingest_repo.py` — CLI entrypoint: `uv run python
  ../scripts/ingest_repo.py <path-or-url> [--repo-id NAME]`, prints a
  summary (files scanned/indexed/skipped, chunks indexed).

No changes were made to `backend/services/vectorstore.py`, Docker Compose, or
any database schema — out of scope for this phase. Embeddings use Chroma's
built-in default embedding function (ONNX MiniLM via `onnxruntime`, already
a `chromadb` dependency since Phase 1) — zero new embedding dependencies.

## New dependencies

`tree-sitter`, `tree-sitter-language-pack` (added via `uv add` in
`backend/`). The language pack downloads each language's compiled grammar
on first use and caches it locally (`~/Library/Caches/tree-sitter-language-pack/`
on macOS) — the very first ingest of a repo containing, say, Python and
JavaScript needs network access twice (once per language); every run after
that is fully offline for those languages.

## How to run it

```bash
docker compose -f docker/docker-compose.yml up -d chroma   # vector DB only, needed by the CLI
cd backend
uv run python ../scripts/ingest_repo.py /path/to/some/repo
# or: uv run python ../scripts/ingest_repo.py https://github.com/org/repo.git
```

Output looks like:

```
repo_id:        hcp-crm
files_scanned:  37
files_indexed:  31
files_skipped:  6
chunks_indexed: 169
```

To spot-check what landed in Chroma:

```python
import chromadb
client = chromadb.HttpClient(host="localhost", port=8001)
col = client.get_collection("hcp-crm")
print(col.count())
print(col.peek(limit=3))
```

Tests (fully offline, no Docker/network — see "Bugs found and fixed" for why):

```bash
cd backend
uv run pytest ../tests -v
```

## File filtering

**Directories never walked into:** `.git`, `.venv`, `venv`, `env`,
`node_modules`, `dist`, `build`, `.next`, `__pycache__`, `.mypy_cache`,
`.pytest_cache`, `.idea`, `.vscode`, `.cache`, `.tox`, any `*.egg-info`.

**Files never read/embedded, regardless of directory** (secret-shaped
filenames): anything starting with `.env` (`.env`, `.env.local`,
`.env.production`, ...), `id_rsa`/`id_ed25519`/`id_ecdsa`/`id_dsa`,
`.npmrc`, `.pypirc`, `.netrc`, `credentials.json`, and anything ending in
`.pem`, `.key`, `.p12`, `.pfx`, `.crt`, `.cer`.

**Other skips:** files over ~1MB, files that fail UTF-8 decode (binary).

No `.gitignore` parsing this phase (would need a new dependency, e.g.
`pathspec`) — the denylist above is a scoped, dependency-free default.

## Bugs found and fixed during real-repo verification

Running against `hcp-crm` (not a synthetic fixture) surfaced two real bugs
that the offline unit tests alone didn't catch:

1. **Duplicate chunk IDs crashed the upsert.** The original chunk ID used
   1-indexed line ranges (`start_line-end_line`). Tree-sitter's chunk
   boundaries are byte-precise and can land mid-line — e.g. `export default
   function Foo()` on one physical line got split into two chunks, both
   computing to the same line range, so two different chunks produced the
   identical ID and Chroma rejected the batch with `DuplicateIDError`. Fixed
   by keying chunk IDs on `start_byte`/`end_byte` (always unique) instead of
   line numbers, while still deriving correct `start_line`/`end_line` from
   those byte offsets for citation metadata.
2. **Real secrets got embedded.** `backend/.env` and `frontend/.env` in the
   test repo contain a live Groq API key and a database URL; before the
   filename denylist existed, both were read, chunked, and indexed into
   Chroma as searchable text. Fixed by adding the secret-filename denylist
   above, applied before any file is even opened. The already-tainted test
   collection was deleted and re-ingested clean; verified the literal key
   string is no longer present in any indexed document.
3. **A related, separate discovery during planning** (not a code bug, just
   a wrong assumption): the test repo has a plain `venv/` directory (not
   `.venv`), which the original directory denylist didn't cover — caught
   during exploration before writing any code, denylist updated accordingly.

**If you point this at your own repo:** double-check nothing sensitive slips
through a filename pattern the denylist doesn't anticipate (e.g. a
custom-named secrets file) before treating the resulting vector DB as safe
to query broadly.

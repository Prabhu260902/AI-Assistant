# Phase 4 — Code Search Agent

## What this phase adds

Given a repo already ingested by Phase 2 (Chroma-indexed chunks), the
backend can now answer natural-language questions about it: hybrid
(vector + keyword) retrieval over the repo's chunks, summarized into an
answer by the LLM, with file/line citations pointing back to the exact
retrieved chunks. First real use of `backend/services/llm.py` (built in
Phase 1, never actually called until now) and the first real content in
`backend/agents/`/`backend/graphs/`/`backend/prompts/` beyond Phase 1's
passthrough example.

- `backend/services/keyword_search.py` — hand-rolled BM25 (`k1=1.5, b=0.75`,
  no external dependency). Tokenizes on non-alphanumerics *and* camelCase
  boundaries, so code identifiers are searchable by their component words
  (`create_hcp` / `createHcp` both tokenize to `["create", "hcp"]`) — a
  naive `\w+` tokenizer would treat `create_hcp` as one opaque token and
  never match a query like "create hcp" at all.
- `backend/services/hybrid_search.py` — `search_repo(repo_id, query, top_k)`:
  runs Chroma's vector query and BM25 keyword search over the same repo's
  chunks, combines the two rankings via **Reciprocal Rank Fusion**
  (`1/(k+rank)`, k=60) rather than trying to normalize cosine distance and
  BM25 score onto a shared scale. Returns chunk content + metadata
  (file/line/language, already stored per-chunk since Phase 2).
- `backend/prompts/code_search.py` — formats retrieved chunks as numbered,
  labeled blocks (`[1] file.py:10-25`) and instructs the model to answer
  using only that context and cite by bracket number.
- `backend/agents/code_search.py` — `retrieve_node` (calls hybrid search)
  and `generate_node` (builds the prompt, calls the LLM, attaches citations
  sourced from the retrieved chunks themselves — not parsed back out of the
  LLM's free-text answer, which would be fragile). Skips the LLM call
  entirely when retrieval finds nothing.
- `backend/graphs/code_search.py` — wires `retrieve → generate` as a
  LangGraph `StateGraph`, mirroring `graphs/passthrough.py`'s pattern from
  Phase 1. `run_code_search(repo_id, query, top_k=5)` is the entry point.
- `backend/main.py` — new `POST /search` endpoint:
  `{repo_id, query, top_k?}` → `{answer, citations: [{file_path, start_line, end_line, snippet}]}`.

## How to run it

```bash
docker compose -f docker/docker-compose.yml up -d chroma
# repo must already be ingested — see docs/phase2.md if not:
# cd backend && uv run python ../scripts/ingest_repo.py /path/to/repo

cd backend
uv run uvicorn main:app --reload
```

```bash
curl -X POST localhost:8000/search \
  -H "Content-Type: application/json" \
  -d '{"repo_id": "hcp-crm", "query": "What does the create_hcp function do?", "top_k": 5}'
```

Or call the graph directly (e.g. in a script/REPL):

```python
from graphs.code_search import run_code_search
state = run_code_search("hcp-crm", "What does the create_hcp function do?", top_k=5)
print(state["answer"])
```

Requires `GROQ_API_KEY` set (`config/.env`) for real LLM calls; retrieval
itself (`hybrid_search.search_repo`) works without it.

Tests (fully offline — no Docker, no network, no real LLM):

```bash
cd backend
uv run pytest ../tests -v
```

## Real bugs found and fixed during verification

1. **Naive tokenizer made BM25 useless for code.** `create_hcp` as a single
   `\w+` token meant a query like "create hcp" never matched it at all —
   the single biggest thing keyword search needs to work for source code.
   Fixed by splitting on non-alphanumerics *and* camelCase boundaries
   (caught before it ever reached a real repo, via a quick manual sanity
   check — worth calling out since it would have made the "keyword" half of
   hybrid search silently useless).
2. **Chroma's `EphemeralClient()` shares state across instances in the same
   process.** Multiple test files independently using a collection named
   `"test-repo"` were unknowingly reading/writing the *same* underlying
   in-memory collection (confirmed: two separate `EphemeralClient()`
   objects, not `is`-identical, but a document added via one was visible
   through the other) — Chroma appears to cache its backing system by a
   hash of `Settings`, and default `EphemeralClient()` settings hash the
   same every time. Caused two unrelated test failures with mismatched
   counts. Fixed by giving every test file its own unique collection name;
   worth knowing if adding more Chroma-backed tests later.
3. **Groq's API silently 403'd every real call.** `services/llm.py`'s
   `GroqProvider` (written in Phase 1, never actually exercised with a real
   network call until this phase) sends no `User-Agent` header, so
   `urllib`'s default (`Python-urllib/3.12`) was blocked by Cloudflare
   (sitting in front of Groq's API) as a bot — Cloudflare error 1010, not a
   Groq-level auth error, confirmed by reading the raw response body rather
   than trusting the generic `HTTP 403 Forbidden` message. Fixed by adding
   an explicit `User-Agent` header. This had been a latent bug since Phase 1;
   nothing before this phase ever actually called the LLM.

## Known limitations

- Keyword search fetches *all* chunks for a repo via `collection.get()` and
  scores them in-memory on every query — fine at current scale (a few
  hundred chunks), would need a real inverted index or a search engine at
  much larger scale.
- Retrieval quality depends heavily on query phrasing matching either the
  embedding's semantic notion of similarity or actual identifier text —
  confirmed in practice: "How does creating a new HCP work?" missed the
  real `create_hcp` handler in the top 5 results, while "What does the
  `create_hcp` function do?" found it cleanly. The LLM correctly avoided
  hallucinating in the first case ("more information is needed") rather
  than inventing an answer — but the retrieval itself is not tuned beyond
  Phase 2's default embedding function and hand-rolled BM25.
- Citations are the full set of chunks passed to the LLM as context, not a
  parsed subset of what it actually cited in the answer text.

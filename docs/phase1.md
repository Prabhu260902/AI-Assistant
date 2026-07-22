# Phase 1 — Foundation

> For a detailed, file-by-file walkthrough of every piece built in this
> phase and a full step-by-step testing guide, see
> [`phase1-walkthrough.md`](phase1-walkthrough.md).

## What this phase adds

- Repository scaffolding matching the target structure (`backend/`, `frontend/`,
  `docs/`, `tests/`, `docker/`, `scripts/`, `config/`).
- A FastAPI backend (`backend/main.py`) with:
  - `GET /health` — liveness check.
  - `POST /graph/invoke` — runs a minimal LangGraph graph end-to-end.
- A minimal LangGraph graph (`backend/graphs/passthrough.py`) with a single
  node that echoes its input to output — proves the graph runtime wiring
  (state → node → compile → invoke) before later phases add real agents.
- Config management (`backend/services/config.py`): a `pydantic-settings`
  class reading env vars, with `config/.env.example` documenting every
  variable. Copy it to `config/.env` for local (non-Docker) runs.
- Structured (JSON) logging (`backend/services/logging.py`), initialized once
  at app startup.
- Two provider-swap interfaces, stubbed for this phase and filled in by later
  phases:
  - `backend/services/llm.py` — `LLMProvider` protocol + a Groq-backed
    implementation (serving Llama 3.3 70B). Swapping providers/models is a
    `LLM_PROVIDER`/`GROQ_MODEL` env var change, not a code change in callers.
  - `backend/services/vectorstore.py` — `VectorStore` protocol + a
    Chroma-backed implementation. The planned Chroma→Qdrant migration is a
    `VECTOR_STORE_PROVIDER` change plus a new adapter class, not a rewrite of
    calling code.
- Docker Compose (`docker/docker-compose.yml`) running `backend` + `postgres`
  + `chroma` together, each with health checks.
- A minimal Next.js (App Router, TypeScript, pnpm) frontend scaffold in
  `frontend/` — confirms the frontend toolchain boots; no feature UI yet.
- Tests in `tests/backend/` covering the health endpoint and the passthrough
  graph (both direct invocation and via the FastAPI endpoint).

## How to run it

### Option A — Docker Compose (full stack)

```bash
cp config/.env.example config/.env   # fill in GROQ_API_KEY if you want real LLM calls
docker compose -f docker/docker-compose.yml --env-file config/.env up --build
```

Then:

```bash
curl localhost:8000/health
curl -X POST localhost:8000/graph/invoke -H "Content-Type: application/json" -d '{"input": "hello"}'
```

### Option B — Backend only, local (no Docker)

```bash
cd backend
uv sync
uv run uvicorn main:app --reload
```

### Frontend

```bash
cd frontend
pnpm install
pnpm dev   # http://localhost:3000
```

### Tests

```bash
cd backend
uv run pytest ../tests
```

## Config reference

All variables are documented in `config/.env.example`. Key ones:

| Variable | Purpose |
|---|---|
| `LLM_PROVIDER`, `GROQ_API_KEY`, `GROQ_MODEL` | LLM adapter config (Groq/Llama 3.3 70B) |
| `DATABASE_URL` | Postgres connection string |
| `VECTOR_STORE_PROVIDER`, `CHROMA_HOST`, `CHROMA_PORT` | Vector store adapter config |
| `LANGSMITH_TRACING`, `LANGSMITH_API_KEY`, `LANGSMITH_PROJECT` | LangSmith tracing |
| `LOG_LEVEL` | Structured logging level |

## Notes / scope boundaries

- The LLM and vector store adapters are wired but not yet exercised by the
  graph — Phase 2 (repository parsing/embedding/indexing) is the first
  consumer of `vectorstore.py`, and later agent phases are the first
  consumers of `llm.py`.
- `backend/agents/`, `backend/tools/`, `backend/memory/`, `backend/prompts/`
  are intentionally empty (`.gitkeep`) — populated starting Phase 4+.
- Nothing AllEase-specific lives in this code; the graph, config, and
  adapters work against any repo/provider.

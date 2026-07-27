# Phase 1 — Deep Dive: What Was Built & How to Test It

This is the detailed, file-by-file companion to [`phase1.md`](phase1.md) (the
quick-reference). Read this if you want to understand *exactly* what each
piece does and why, or if you need to verify Phase 1 is actually working.

---

## 1. The goal of Phase 1

Prove the skeleton works end-to-end before any real intelligence is added:
a request can enter through FastAPI, flow through a compiled LangGraph
graph, and come back out — with config, logging, and the future swap points
(LLM provider, vector store) already wired in as interfaces. Nothing in this
phase is AllEase-specific; it would behave identically pointed at any repo.

---

## 2. Repository layout created

```
backend/
  agents/        empty (.gitkeep) — first used in Phase 4+
  graphs/        passthrough.py, __init__.py
  tools/         empty (.gitkeep) — first used in later phases
  memory/        empty (.gitkeep) — first used in later phases
  prompts/       empty (.gitkeep) — first used in later phases
  services/      config.py, logging.py, llm.py, vectorstore.py, __init__.py
  state/         graph_state.py, __init__.py
  main.py        FastAPI entrypoint
  pyproject.toml / uv.lock / .python-version   (uv-managed Python project)
frontend/        minimal Next.js (App Router, TS, pnpm) scaffold
docs/
  phase1.md               quick-reference (run commands, config table)
  phase1-walkthrough.md   this file
tests/
  conftest.py              puts backend/ on sys.path so tests can import it
  backend/test_health.py
  backend/test_graph.py
docker/
  docker-compose.yml       backend + postgres + chroma
  backend.Dockerfile
config/
  .env.example             every env var, documented, no real secrets
.dockerignore               at REPO ROOT (see §7 for why that matters)
.gitignore                  at repo root
```

`backend/` is its own **uv project root** — its `pyproject.toml`/`uv.lock`/
`.venv` live inside `backend/`, not at the repo root. That's why every
backend Python file imports modules as `services.config`, `graphs.passthrough`,
etc. — **not** `backend.services.config`. `backend/` itself is the import
root, the same way it's the uv project root.

---

## 3. Backend, file by file

### `backend/services/config.py` — configuration

A single `pydantic-settings` `Settings` class. Every setting has a sane
default, so the app boots with zero configuration; real values (API keys,
etc.) come from environment variables or `config/.env`.

```python
_ENV_FILE = _REPO_ROOT / "config" / ".env"   # optional — only read if it exists
```

Key fields: `app_name`, `environment`, `log_level`, `llm_provider`,
`groq_api_key`, `groq_model`, `database_url`, `vector_store_provider`,
`chroma_host`, `chroma_port`, `langsmith_tracing`, `langsmith_api_key`,
`langsmith_project`.

`get_settings()` is `@lru_cache`d — settings are read once per process, not
re-parsed on every call.

**Why it matters:** every other module reads config through this one place.
Nothing hardcodes an API key, host, or model name.

### `backend/services/logging.py` — structured logging

A `JsonFormatter` that turns every log record into one JSON line
(`timestamp`, `level`, `logger`, `message`, and `exception` if present).
`configure_logging()` installs it on the root logger and is called once,
at app startup, from `main.py`. You saw this in the container logs:

```json
{"timestamp": "2026-07-21T18:26:58.431535+00:00", "level": "INFO", "logger": "main", "message": "Application startup: allease-engineering-assistant (development)"}
```

### `backend/services/llm.py` — the LLM provider interface

```python
class LLMProvider(Protocol):
    def complete(self, prompt: str) -> str: ...

class GroqProvider:
    def complete(self, prompt: str) -> str: ...   # calls Groq's chat completions API

def get_llm_provider() -> LLMProvider:
    ...  # reads settings.llm_provider, returns the matching implementation
```

`GroqProvider` calls Groq's OpenAI-compatible endpoint
(`https://api.groq.com/openai/v1/chat/completions`) using nothing but
Python's stdlib `urllib.request` — no extra HTTP dependency was needed.
**Not called anywhere yet** — the passthrough graph doesn't need an LLM.
This exists so that later phases (5+, agents that actually think) depend on
`LLMProvider`/`get_llm_provider()`, never on Groq directly. Swapping models
or providers later is a `LLM_PROVIDER`/`GROQ_MODEL` env var change plus one
new class here — not a rewrite of every caller.

### `backend/services/vectorstore.py` — the vector store interface

Same pattern:

```python
class VectorStore(Protocol):
    def get_or_create_collection(self, name: str) -> Any: ...

class ChromaVectorStore:
    def __init__(self, host: str, port: int) -> None:
        self._client = chromadb.HttpClient(host=host, port=port)
    ...

def get_vector_store() -> VectorStore:
    ...  # reads settings.vector_store_provider
```

Connects to the Chroma service over HTTP (matches the `chroma` container in
Docker Compose). **Not populated with embeddings yet** — that's Phase 2's
job. The point of this phase is only that the connection/interface exists,
so the planned Chroma→Qdrant migration is "write a `QdrantVectorStore` class
+ flip `VECTOR_STORE_PROVIDER`," not "rewrite every place that touched
Chroma."

### `backend/state/graph_state.py` — shared graph state schema

```python
class PassthroughState(TypedDict):
    input: str
    output: str
```

LangGraph state schemas live in `state/` so later phases' agent/graph state
shapes have one obvious home.

### `backend/graphs/passthrough.py` — the actual LangGraph graph

```python
def passthrough_node(state: PassthroughState) -> PassthroughState:
    return {"input": state["input"], "output": state["input"]}

def build_passthrough_graph():
    graph = StateGraph(PassthroughState)
    graph.add_node("passthrough", passthrough_node)
    graph.add_edge(START, "passthrough")
    graph.add_edge("passthrough", END)
    return graph.compile()

_compiled_graph = build_passthrough_graph()

def run_passthrough(input_text: str) -> str:
    result = _compiled_graph.invoke({"input": input_text, "output": ""})
    return result["output"]
```

This is deliberately trivial: one node, `START → passthrough → END`, and the
node just copies `input` to `output`. It exists to prove the LangGraph
runtime plumbing (state schema → node → compiled graph → `.invoke()`) works
before any real agent logic is built on top of it in Phase 4+. The graph is
compiled **once** at import time (`_compiled_graph`), not on every request.

### `backend/main.py` — the FastAPI app

```python
def create_app() -> FastAPI:
    configure_logging()
    _configure_langsmith()
    settings = get_settings()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        logger.info("Application startup: %s (%s)", settings.app_name, settings.environment)
        yield

    app = FastAPI(title=settings.app_name, lifespan=lifespan)

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok"}

    @app.post("/graph/invoke", response_model=GraphInvokeResponse)
    async def graph_invoke(request: GraphInvokeRequest) -> GraphInvokeResponse:
        output = run_passthrough(request.input)
        return GraphInvokeResponse(output=output)

    return app

app = create_app()
```

- Uses the modern `lifespan` context-manager pattern (not the deprecated
  `@app.on_event("startup")`) — this was fixed during Phase 1 after the
  first pytest run flagged it as a deprecation warning.
- `_configure_langsmith()` sets `LANGCHAIN_TRACING_V2` / `LANGCHAIN_API_KEY` /
  `LANGCHAIN_PROJECT` env vars from settings, because LangChain/LangGraph's
  tracing picks those up automatically — no explicit tracing code needed
  elsewhere.
- Two routes only: `GET /health` (liveness) and `POST /graph/invoke`
  (`{"input": "..."}` → `{"output": "..."}`), which runs the compiled
  passthrough graph.

### `backend/pyproject.toml` — dependencies

Runtime: `fastapi`, `uvicorn[standard]`, `langgraph`, `langchain-core`,
`pydantic-settings`, `sqlalchemy`, `psycopg[binary]`, `chromadb`, `langsmith`,
`python-dotenv`.
Dev: `pytest`, `httpx` (for FastAPI's `TestClient`).
Managed by `uv` — `uv.lock` pins exact versions.

---

## 4. Frontend

`frontend/` is a stock `create-next-app` output: App Router, TypeScript,
ESLint, no Tailwind, pnpm as the package manager. It has no real UI yet —
Phase 1's job was only to prove `pnpm install && pnpm dev`/`pnpm build`
works. One non-obvious fix was needed here too: `pnpm-workspace.yaml`'s
`allowBuilds` had to be explicitly set to `true` for `sharp` and
`unrs-resolver` (Next.js's native postinstall deps) — pnpm now refuses to
run install scripts for a package until you approve them.

---

## 5. Docker Compose stack

`docker/docker-compose.yml` defines three services:

| Service | Image | Port (host→container) | Healthcheck |
|---|---|---|---|
| `postgres` | `postgres:16-alpine` | 55432→5432 | `pg_isready` |
| `chroma` | `chromadb/chroma:latest` | 8001→8000 | bash TCP check on port 8000 (see §7) |
| `backend` | built from `docker/backend.Dockerfile` | 8000→8000 | — (depends on the other two being healthy) |

`postgres`'s host port was moved from the default 5432 to 55432 in Phase 3, after discovering a locally-installed (non-Docker) Postgres on the host was already bound to 5432 and silently intercepting connections meant for the container. Container-to-container traffic (e.g. the `backend` service's own `DATABASE_URL`) still uses the internal port 5432 — only the host-facing mapping changed.

`backend` only starts after both `postgres` and `chroma` report healthy
(`depends_on: condition: service_healthy`). Its env vars are populated from
the host shell via `${VAR:-default}` substitution — nothing is hardcoded,
and there's no dependency on a `config/.env` file existing (Compose would
fail hard if a referenced `env_file` didn't exist; this design sidesteps
that entirely).

`docker/backend.Dockerfile`:

```dockerfile
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
ENV UV_PYTHON_PREFERENCE=only-system
WORKDIR /app
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev
COPY backend/ .
EXPOSE 8000
CMD [".venv/bin/uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

Two lines here exist specifically because of bugs hit and fixed during
Phase 1 verification — see §7, worth reading if you ever touch this file.

---

## 6. Tests

`tests/conftest.py` inserts `backend/` onto `sys.path` (by absolute path, so
it works regardless of where pytest is invoked from), so `tests/backend/*.py`
can `from main import app` and `from graphs.passthrough import run_passthrough`
exactly like `main.py` itself does.

- `tests/backend/test_health.py` — asserts `GET /health` returns
  `200 {"status": "ok"}`.
- `tests/backend/test_graph.py` — asserts `run_passthrough("hello world")`
  returns `"hello world"` directly, **and** that `POST /graph/invoke` returns
  the same thing through the HTTP layer (via `TestClient`, in-process, no
  real network call).

3 tests, all passing, no network/Docker required to run them.

---

## 7. Two real bugs hit and fixed (worth knowing if they resurface)

1. **Chroma healthcheck failed.** The initial healthcheck assumed Python +
   `urllib` existed inside the `chromadb/chroma` image to hit its HTTP
   heartbeat endpoint. That image is minimal and has neither Python nor
   `curl`/`wget` — only `bash`. Fixed by using a pure-bash TCP check:
   `bash -c "exec 3<>/dev/tcp/localhost/8000"` (note: must be `CMD` with
   explicit `bash -c`, not `CMD-SHELL`, since `CMD-SHELL` runs under `/bin/sh`
   which doesn't support `/dev/tcp`).

2. **The Mac's `.venv` leaked into the Linux image.** `docker-compose.yml`
   sets `context: ..` (repo root) for the backend build, but the original
   `.dockerignore` lived at `backend/.dockerignore`. Docker only reads a
   `.dockerignore` at the **build context root** — so it was silently
   ignored, and `backend/.venv` (built locally on macOS, with script shebangs
   like `#!/Users/.../backend/.venv/bin/python`) got copied straight into the
   image, overwriting the correct Linux venv that `RUN uv sync` had just
   built. Symptom: container logs showed `uv run` "self-healing" by
   recreating the entire venv on every container start; after switching the
   `CMD` to invoke the venv binary directly (`.venv/bin/uvicorn`, bypassing
   `uv run`'s runtime checks), it failed outright with
   `exec .venv/bin/uvicorn: no such file or directory`, which is what
   exposed the real cause. Fixed by moving `.dockerignore` to the repo root
   (excluding `backend/.venv`, `frontend/node_modules`, etc.) and adding
   `ENV UV_PYTHON_PREFERENCE=only-system` so the container always builds its
   venv against the base image's system Python, never a downloaded one.

---

## 8. How to test Phase 1 — step by step

### 8a. Automated tests (fastest, no Docker needed)

```bash
cd backend
uv sync                     # first time only, or after pulling dependency changes
uv run pytest ../tests -v
```

**Expected:** `3 passed`. This alone confirms the graph, the FastAPI routes,
and config/logging all import and run correctly.

### 8b. Backend only, running locally (no Docker)

```bash
cd backend
uv run uvicorn main:app --reload
```

In another terminal:

```bash
curl localhost:8000/health
# {"status":"ok"}

curl -X POST localhost:8000/graph/invoke \
  -H "Content-Type: application/json" \
  -d '{"input": "hello"}'
# {"output":"hello"}
```

Vector store and LLM calls are **not** exercised by this path — Postgres and
Chroma aren't even running — which is expected for Phase 1.

### 8c. Full stack via Docker Compose (the real end-to-end test)

```bash
cp config/.env.example config/.env   # fill in GROQ_API_KEY if you want it available; not required for Phase 1
docker compose -f docker/docker-compose.yml --env-file config/.env up --build
```

**Expected in the logs**, in order: `postgres` becomes healthy, `chroma`
becomes healthy, then `backend` starts — you should see the structured
startup log line and *no* "recreating virtual environment" messages:

```json
{"timestamp": "...", "level": "INFO", "logger": "main", "message": "Application startup: allease-engineering-assistant (development)"}
INFO:     Uvicorn running on http://0.0.0.0:8000
```

In another terminal, confirm all three containers are healthy:

```bash
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
```

All three should show `Up ... (healthy)` (backend has no healthcheck defined,
so it'll show `Up ...` without a health annotation — that's fine, it only
starts after the other two pass their checks).

Then hit the real endpoints:

```bash
curl -sS -w "\nHTTP %{http_code}\n" localhost:8000/health
# {"status":"ok"}
# HTTP 200

curl -sS -w "\nHTTP %{http_code}\n" -X POST localhost:8000/graph/invoke \
  -H "Content-Type: application/json" -d '{"input": "docker test"}'
# {"output":"docker test"}
# HTTP 200
```

Tear down when done:

```bash
docker compose -f docker/docker-compose.yml down
rm config/.env   # don't leave a real .env sitting around if you don't need it
```

### 8d. Frontend boots

```bash
cd frontend
pnpm install
pnpm build     # confirms it compiles cleanly
pnpm dev       # http://localhost:3000 — should show the default Next.js starter page
```

### 8e. Full "is Phase 1 actually done" checklist

- [ ] `uv run pytest ../tests` → 3 passed
- [ ] `docker compose up --build` → all three containers reach a healthy/running state
- [ ] `curl localhost:8000/health` → `200 {"status":"ok"}`
- [ ] `curl -X POST localhost:8000/graph/invoke -d '{"input": "x"}'` → `200 {"output":"x"}`
- [ ] Backend container logs show one clean structured JSON startup line, no venv-recreation warnings
- [ ] `pnpm build` in `frontend/` succeeds
- [ ] No AllEase-specific strings/logic anywhere in `backend/` (grep for "allease" — the only hits should be the project *name* in `pyproject.toml`/config defaults, not behavior)

If every box above is checked, Phase 1 is done and it's safe to move to
Phase 2.

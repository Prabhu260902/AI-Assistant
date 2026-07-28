"""FastAPI application entrypoint."""

import logging
import os
import re
import subprocess
from contextlib import asynccontextmanager
from dataclasses import asdict, is_dataclass

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import select

from graphs.architecture import run_architecture_explanation
from graphs.code_search import run_code_search
from graphs.feature_planner import run_feature_plan
from graphs.implementation import run_implementation
from graphs.passthrough import run_passthrough
from graphs.pr_review import run_pr_review
from graphs.router import run_copilot
from graphs.ticket_generator import run_generate_tickets
from services.code_apply import ApplyError, FileChange, apply_changes
from services.config import get_settings
from services.db import session_scope
from services.git_diff import GitDiffError
from services.ingest import ingest_repository
from services.knowledge_graph import build_knowledge_graph
from services.logging import configure_logging
from services.models import Repository
from services.repo_registry import get_repo_source
from state.implementation_state import ProposedChange
from state.review_state import Finding
from state.ticket_state import Epic

logger = logging.getLogger(__name__)


class GraphInvokeRequest(BaseModel):
    input: str


class GraphInvokeResponse(BaseModel):
    output: str


class SearchRequest(BaseModel):
    repo_id: str
    query: str
    top_k: int = 5


class Citation(BaseModel):
    file_path: str
    start_line: int
    end_line: int
    snippet: str


class SearchResponse(BaseModel):
    answer: str
    citations: list[Citation]


class PlanRequest(BaseModel):
    repo_id: str
    feature_description: str
    top_k: int = 5


class AffectedModuleModel(BaseModel):
    file_path: str
    reason: str
    fan_in: int
    has_api_endpoint: bool


class PlanResponse(BaseModel):
    plan: str
    affected_modules: list[AffectedModuleModel]
    risks: list[str]


class TicketRequest(BaseModel):
    repo_id: str
    feature_description: str
    top_k: int = 5


class TicketResponse(BaseModel):
    plan: str
    affected_modules: list[AffectedModuleModel]
    risks: list[str]
    epics: list[Epic]


class ImplementRequest(BaseModel):
    repo_id: str
    feature_description: str
    top_k: int = 5


class ImplementResponse(BaseModel):
    plan: str
    risks: list[str]
    proposed_changes: list[ProposedChange]


class FileChangeModel(BaseModel):
    file_path: str
    new_content: str


class ImplementApplyRequest(BaseModel):
    repo_id: str
    changes: list[FileChangeModel]
    branch_name: str


class ImplementApplyResponse(BaseModel):
    branch: str
    files_written: list[str]


class ReviewRequest(BaseModel):
    repo_id: str
    base_ref: str
    head_ref: str


class ReviewResponse(BaseModel):
    summary: str
    findings: list[Finding]


class ArchitectureRequest(BaseModel):
    repo_id: str
    query: str
    top_k: int = 5


class FlowNodeModel(BaseModel):
    key: str
    name: str
    file_path: str
    kind: str
    detail: str | None = None


class FlowEdgeModel(BaseModel):
    from_key: str
    to_key: str


class ArchitectureResponse(BaseModel):
    explanation: str
    mermaid_diagram: str
    nodes: list[FlowNodeModel]
    edges: list[FlowEdgeModel]


class CopilotRequest(BaseModel):
    repo_id: str
    message: str
    top_k: int = 5


class CopilotResponse(BaseModel):
    intent: str
    result: dict


class IngestRequest(BaseModel):
    source: str
    repo_id: str | None = None


class IngestResponse(BaseModel):
    repo_id: str
    files_scanned: int
    files_indexed: int
    files_skipped: int
    chunks_indexed: int
    files: int
    symbols: int
    imports: int
    calls: int
    endpoints: int


class RepoListResponse(BaseModel):
    repos: list[str]


# Mirrors Chroma's own collection-name rule (services/vectorstore.py ultimately
# hands repo_id straight to Chroma as the collection name) — validated here so
# a bad custom repo_id fails with a clear 400 instead of the generic 500 the
# global exception handler below would otherwise produce.
_REPO_ID_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{1,510}[a-zA-Z0-9]$")


def _to_jsonable(value):
    if is_dataclass(value) and not isinstance(value, type):
        return _to_jsonable(asdict(value))
    if isinstance(value, BaseModel):
        return value.model_dump()
    if isinstance(value, list):
        return [_to_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {key: _to_jsonable(item) for key, item in value.items()}
    return value


def _configure_langsmith() -> None:
    settings = get_settings()
    os.environ["LANGCHAIN_TRACING_V2"] = str(settings.langsmith_tracing).lower()
    if settings.langsmith_api_key:
        os.environ["LANGCHAIN_API_KEY"] = settings.langsmith_api_key
    os.environ["LANGCHAIN_PROJECT"] = settings.langsmith_project


def create_app() -> FastAPI:
    configure_logging()
    _configure_langsmith()

    settings = get_settings()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        logger.info("Application startup: %s (%s)", settings.app_name, settings.environment)
        yield

    app = FastAPI(title=settings.app_name, lifespan=lifespan)

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        # Starlette's own default for an uncaught exception is a plain-text
        # "Internal Server Error" body, not JSON — every client in this
        # project (including the frontend's proxy route) expects a JSON
        # response even on failure, so this ensures that holds everywhere.
        logger.error("Unhandled exception on %s %s", request.method, request.url.path, exc_info=exc)
        return JSONResponse(status_code=500, content={"detail": "Internal server error."})

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok"}

    @app.post("/graph/invoke", response_model=GraphInvokeResponse)
    async def graph_invoke(request: GraphInvokeRequest) -> GraphInvokeResponse:
        output = run_passthrough(request.input)
        return GraphInvokeResponse(output=output)

    @app.post("/search", response_model=SearchResponse)
    async def search(request: SearchRequest) -> SearchResponse:
        result = run_code_search(request.repo_id, request.query, request.top_k)
        return SearchResponse(answer=result["answer"], citations=result["citations"])

    @app.post("/plan", response_model=PlanResponse)
    async def plan(request: PlanRequest) -> PlanResponse:
        result = run_feature_plan(request.repo_id, request.feature_description, request.top_k)
        return PlanResponse(
            plan=result["plan"],
            affected_modules=[asdict(module) for module in result["affected_modules"]],
            risks=result["risks"],
        )

    @app.post("/tickets", response_model=TicketResponse)
    async def tickets(request: TicketRequest) -> TicketResponse:
        result = run_generate_tickets(request.repo_id, request.feature_description, request.top_k)
        return TicketResponse(
            plan=result["plan"],
            affected_modules=[asdict(module) for module in result["affected_modules"]],
            risks=result["risks"],
            epics=result["epics"],
        )

    @app.post("/implement", response_model=ImplementResponse)
    async def implement(request: ImplementRequest) -> ImplementResponse:
        """Dry run only — retrieves, plans, and proposes diffs. Writes nothing."""
        result = run_implementation(request.repo_id, request.feature_description, request.top_k)
        return ImplementResponse(
            plan=result["plan"],
            risks=result["risks"],
            proposed_changes=result["proposed_changes"],
        )

    @app.post("/implement/apply", response_model=ImplementApplyResponse)
    async def implement_apply(request: ImplementApplyRequest) -> ImplementApplyResponse:
        """Writes files to disk on a new git branch. Call only after reviewing
        the diffs from /implement — nothing here is auto-approved."""
        repo_source = get_repo_source(request.repo_id)
        if repo_source is None:
            raise HTTPException(status_code=404, detail=f"Unknown repo_id: {request.repo_id}")

        try:
            summary = apply_changes(
                repo_source,
                [FileChange(file_path=c.file_path, new_content=c.new_content) for c in request.changes],
                request.branch_name,
            )
        except ApplyError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

        return ImplementApplyResponse(branch=summary.branch, files_written=summary.files_written)

    @app.post("/review", response_model=ReviewResponse)
    async def review(request: ReviewRequest) -> ReviewResponse:
        try:
            result = run_pr_review(request.repo_id, request.base_ref, request.head_ref)
        except GitDiffError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        return ReviewResponse(summary=result["summary"], findings=result["findings"])

    @app.post("/architecture", response_model=ArchitectureResponse)
    async def architecture(request: ArchitectureRequest) -> ArchitectureResponse:
        result = run_architecture_explanation(request.repo_id, request.query, request.top_k)
        flow_graph = result["flow_graph"]
        nodes = [asdict(n) for n in flow_graph.nodes] if flow_graph else []
        edges = [asdict(e) for e in flow_graph.edges] if flow_graph else []
        return ArchitectureResponse(
            explanation=result["explanation"],
            mermaid_diagram=result["mermaid_diagram"],
            nodes=nodes,
            edges=edges,
        )

    @app.post("/copilot", response_model=CopilotResponse)
    async def copilot(request: CopilotRequest) -> CopilotResponse:
        try:
            state = run_copilot(request.repo_id, request.message, request.top_k)
        except GitDiffError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        return CopilotResponse(intent=state["intent"], result=_to_jsonable(state["result"]))

    @app.post("/repos", response_model=IngestResponse)
    async def add_repo(request: IngestRequest) -> IngestResponse:
        """Ingest a repo (local path or git URL) into both the vector store
        and the knowledge graph — the same two steps scripts/ingest_repo.py
        already runs, just reachable over HTTP so the chat UI's /ingest
        command doesn't need a terminal."""
        if request.repo_id and not _REPO_ID_RE.match(request.repo_id):
            raise HTTPException(
                status_code=400,
                detail="repo_id must be 3-512 characters, letters/digits/._- only, "
                "starting and ending with a letter or digit.",
            )
        try:
            vector_summary = ingest_repository(request.source, repo_id=request.repo_id)
            graph_summary = build_knowledge_graph(request.source, repo_id=vector_summary.repo_id)
        except (ValueError, subprocess.CalledProcessError) as exc:
            raise HTTPException(status_code=400, detail=f"Could not ingest '{request.source}': {exc}") from exc

        return IngestResponse(
            repo_id=vector_summary.repo_id,
            files_scanned=vector_summary.files_scanned,
            files_indexed=vector_summary.files_indexed,
            files_skipped=vector_summary.files_skipped,
            chunks_indexed=vector_summary.chunks_indexed,
            files=graph_summary.files,
            symbols=graph_summary.symbols,
            imports=graph_summary.imports,
            calls=graph_summary.calls,
            endpoints=graph_summary.endpoints,
        )

    @app.get("/repos", response_model=RepoListResponse)
    async def list_repos() -> RepoListResponse:
        with session_scope() as session:
            repo_ids = session.execute(select(Repository.repo_id).order_by(Repository.repo_id)).scalars().all()
        return RepoListResponse(repos=list(repo_ids))

    return app


app = create_app()

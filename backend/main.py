"""FastAPI application entrypoint."""

import logging
import os
from contextlib import asynccontextmanager
from dataclasses import asdict

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from graphs.architecture import run_architecture_explanation
from graphs.code_search import run_code_search
from graphs.feature_planner import run_feature_plan
from graphs.implementation import run_implementation
from graphs.passthrough import run_passthrough
from graphs.pr_review import run_pr_review
from graphs.ticket_generator import run_generate_tickets
from services.code_apply import ApplyError, FileChange, apply_changes
from services.config import get_settings
from services.git_diff import GitDiffError
from services.logging import configure_logging
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

    return app


app = create_app()

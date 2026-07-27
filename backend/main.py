"""FastAPI application entrypoint."""

import logging
import os
from contextlib import asynccontextmanager
from dataclasses import asdict

from fastapi import FastAPI
from pydantic import BaseModel

from graphs.code_search import run_code_search
from graphs.feature_planner import run_feature_plan
from graphs.passthrough import run_passthrough
from graphs.ticket_generator import run_generate_tickets
from services.config import get_settings
from services.logging import configure_logging
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

    return app


app = create_app()

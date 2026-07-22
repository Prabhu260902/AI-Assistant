"""FastAPI application entrypoint."""

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from pydantic import BaseModel

from graphs.passthrough import run_passthrough
from services.config import get_settings
from services.logging import configure_logging

logger = logging.getLogger(__name__)


class GraphInvokeRequest(BaseModel):
    input: str


class GraphInvokeResponse(BaseModel):
    output: str


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

    return app


app = create_app()

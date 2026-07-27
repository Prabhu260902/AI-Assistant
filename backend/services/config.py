"""Centralized application configuration.

Values are sourced from environment variables, falling back to
`config/.env` when present. Docker Compose injects real env vars directly,
so the file is optional for containerized runs and convenient for local dev.
"""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_REPO_ROOT = Path(__file__).resolve().parents[2]
_ENV_FILE = _REPO_ROOT / "config" / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_ENV_FILE if _ENV_FILE.exists() else None,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "allease-engineering-assistant"
    environment: str = "development"
    log_level: str = "INFO"

    llm_provider: str = "groq"
    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"
    # Tried in order if the primary model 429s (rate/quota limited) — each
    # Groq model has its own separate rate-limit bucket, so falling back
    # actually unblocks a request rather than hitting the same wall again.
    groq_fallback_models: list[str] = ["llama-3.1-8b-instant", "openai/gpt-oss-20b"]

    database_url: str = "postgresql+psycopg://allease:allease@localhost:55432/allease"

    vector_store_provider: str = "chroma"
    chroma_host: str = "localhost"
    chroma_port: int = 8001

    langsmith_tracing: bool = False
    langsmith_api_key: str = ""
    langsmith_project: str = "allease-engineering-assistant"


@lru_cache
def get_settings() -> Settings:
    return Settings()

"""Central, env-driven application settings (12-factor style).

All values can be overridden via environment variables or a local `.env`
file (see `.env.example`). Secrets must only ever come from the environment.
"""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    APP_NAME: str = "Algo Backtesting Platform"
    APP_ENV: str = "development"
    LOG_LEVEL: str = "INFO"

    API_V1_PREFIX: str = "/api/v1"
    # pydantic-settings parses complex types from JSON env values.
    CORS_ORIGINS: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    # Phase 3 — used once the database layer is implemented.
    DATABASE_URL: str = (
        "postgresql+psycopg://postgres:postgres@localhost:5432/backtesting"
    )

    # Phase 2 — CSV ingestion limit.
    MAX_UPLOAD_MB: int = 100


@lru_cache
def get_settings() -> Settings:
    """Cached accessor so settings are parsed once per process."""
    return Settings()

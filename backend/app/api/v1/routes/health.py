"""Liveness/readiness endpoint — also used as the Phase 1 smoke test."""
from datetime import datetime, timezone

from fastapi import APIRouter

from app import __version__
from app.core.config import get_settings
from app.schemas.health import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health_check() -> HealthResponse:
    settings = get_settings()
    return HealthResponse(
        status="ok",
        app=settings.APP_NAME,
        version=__version__,
        environment=settings.APP_ENV,
        timestamp=datetime.now(timezone.utc),
    )

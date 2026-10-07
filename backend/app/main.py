"""FastAPI application factory.

Phase 1 scope: settings, logging, CORS, versioned API router with a health
endpoint. Routers for data/strategies/backtests are added in later phases
without touching this file's structure.
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api.v1.router import api_router
from app.backtesting.registry import bootstrap as bootstrap_strategies
from app.core.config import get_settings
from app.core.logging import configure_logging


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.LOG_LEVEL)
    bootstrap_strategies()  # register built-in strategy plugins

    app = FastAPI(
        title=settings.APP_NAME,
        version=__version__,
        description=(
            "Multi-market algorithmic trading backtesting platform. "
            "Research and validation tool — a profitable backtest is not a "
            "guarantee of future performance."
        ),
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(api_router, prefix=settings.API_V1_PREFIX)
    return app


app = create_app()

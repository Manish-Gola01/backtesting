"""Aggregates all v1 route modules behind a single router."""
from fastapi import APIRouter

from app.api.v1.routes import backtests, data, health, optimize, strategies

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(data.router)
api_router.include_router(strategies.router)
api_router.include_router(backtests.router)
api_router.include_router(optimize.router)

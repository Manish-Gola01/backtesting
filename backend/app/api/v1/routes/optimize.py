"""Parameter optimization + walk-forward endpoints (Phases 11-12).

Runs synchronously over already-uploaded in-memory data. Heavy sweeps should
move to the job runner; these endpoints are for research-scale grids.
"""
import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.analytics.optimize import optimize
from app.analytics.walkforward import walk_forward
from app.data import store

router = APIRouter(tags=["optimize"])
logger = logging.getLogger(__name__)


class OptimizeRequest(BaseModel):
    strategy: str
    symbol: str
    exchange: str
    timeframe: str
    initial_capital: float = Field(gt=0)
    param_grid: dict[str, list]
    rank_by: str = "sharpe_ratio"
    base: dict = Field(default_factory=dict)   # sizing/costs/execution overrides
    split: tuple[float, float, float] = (0.6, 0.2, 0.2)
    max_combinations: int = 500


class WalkForwardRequest(BaseModel):
    strategy: str
    symbol: str
    exchange: str
    timeframe: str
    initial_capital: float = Field(gt=0)
    param_grid: dict[str, list]
    train_size: int = Field(gt=0)
    test_size: int = Field(gt=0)
    rank_by: str = "sharpe_ratio"
    anchored: bool = False
    base: dict = Field(default_factory=dict)


def _load(req) -> object:
    ds = store.get(req.symbol.upper(), req.exchange.upper(), req.timeframe)
    if ds is None:
        raise HTTPException(status_code=404, detail=f"no data for {req.symbol}/{req.exchange} {req.timeframe}")
    return ds.frame


def _base_request(req) -> dict:
    b = dict(req.base)
    b.update({
        "strategy": req.strategy, "symbol": req.symbol, "exchange": req.exchange,
        "timeframe": req.timeframe, "initial_capital": req.initial_capital,
        "warmup": b.get("warmup", 0),
    })
    return b


@router.post("/optimize")
def optimize_endpoint(req: OptimizeRequest):
    frame = _load(req)
    try:
        return optimize(frame, _base_request(req), req.param_grid, rank_by=req.rank_by,
                        split=req.split, max_combinations=req.max_combinations)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/walkforward")
def walkforward_endpoint(req: WalkForwardRequest):
    frame = _load(req)
    return walk_forward(frame, _base_request(req), req.param_grid,
                        train_size=req.train_size, test_size=req.test_size,
                        rank_by=req.rank_by, anchored=req.anchored)

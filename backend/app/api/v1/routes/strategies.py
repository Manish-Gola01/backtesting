"""Strategy catalog endpoints."""
from fastapi import APIRouter, HTTPException

from app.backtesting.registry import get_strategy, list_strategies
from app.schemas.backtest import StrategyOut

router = APIRouter(tags=["strategies"])


@router.get("/strategies", response_model=list[StrategyOut])
def list_all() -> list[StrategyOut]:
    return [StrategyOut(**s) for s in list_strategies()]


@router.get("/strategies/{name}", response_model=StrategyOut)
def get_one(name: str) -> StrategyOut:
    try:
        s = get_strategy(name)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"strategy {name!r} not found")
    return StrategyOut(name=s.name, description=s.description, param_schema=dict(s.param_schema))

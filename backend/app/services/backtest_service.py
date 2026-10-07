"""Backtest orchestration: load data -> run engine -> compute metrics.

Returns a plain dict bundle so the API layer can persist/serialize without
touching engine internals. Storage-backend agnostic (uses the active store).
"""
from __future__ import annotations

import logging
from typing import Any

from app.analytics import compute_metrics
from app.backtesting import (
    BacktestConfig, CostModel, ExecutionModel, IntrabarPolicy,
    RiskLimits, SizingModel, SizingSpec, run_backtest,
)
from app.backtesting.registry import get_strategy
from app.data import store

logger = logging.getLogger(__name__)


class DataNotFoundError(Exception):
    pass


def _build_config(req: dict) -> BacktestConfig:
    sizing = req.get("sizing", {})
    costs = req.get("costs", {})
    risk = req.get("risk", {})
    return BacktestConfig(
        strategy=req["strategy"],
        symbol=req["symbol"],
        timeframe=req["timeframe"],
        initial_capital=float(req["initial_capital"]),
        params=req.get("params", {}),
        sizing=SizingSpec(
            model=SizingModel(sizing.get("model", "risk_pct")),
            value=float(sizing.get("value", 1.0)),
            lot_size=sizing.get("lot_size"),
            compounding=bool(sizing.get("compounding", True)),
        ),
        costs=CostModel(
            brokerage_per_trade=float(costs.get("brokerage_per_trade", 0.0)),
            brokerage_pct=float(costs.get("brokerage_pct", 0.0)),
            exchange_fee_pct=float(costs.get("exchange_fee_pct", 0.0)),
            other_charges_pct=float(costs.get("other_charges_pct", 0.0)),
            slippage_pct=float(costs.get("slippage_pct", 0.0)),
        ),
        risk=RiskLimits(
            max_position_size=risk.get("max_position_size"),
            max_open_positions=int(risk.get("max_open_positions", 1)),
            daily_loss_limit=risk.get("daily_loss_limit"),
            max_drawdown_limit=risk.get("max_drawdown_limit"),
        ),
        execution_model=ExecutionModel(req.get("execution_model", "next_open")),
        intrabar_policy=IntrabarPolicy(req.get("intrabar_policy", "conservative")),
        warmup=int(req.get("warmup", req.get("params", {}).get("lookback", 0))),
        stop_loss_pct=req.get("stop_loss_pct"),
        take_profit_pct=req.get("take_profit_pct"),
        risk_reward=req.get("risk_reward"),
    )


def run_backtest_job(req: dict) -> dict[str, Any]:
    """Synchronous workhorse executed by the job runner. Returns a bundle:
    {result, metrics, config}. Raises DataNotFoundError for missing data.
    """
    symbol = req["symbol"].upper()
    exchange = req.get("exchange", "").upper()
    timeframe = req["timeframe"]

    ds = store.get(symbol, exchange, timeframe)
    if ds is None:
        raise DataNotFoundError(
            f"no data for {symbol}/{exchange} {timeframe}; upload a CSV first"
        )
    if req.get("params", {}).get("oi_required", True) and not ds.meta.has_oi:
        raise DataNotFoundError(
            f"{symbol}/{exchange} {timeframe} has no open_interest data but the "
            f"strategy requires it"
        )

    config = _build_config(req)
    strategy = get_strategy(config.strategy)

    logger.info(
        "backtest start: %s %s/%s %s candles=%d",
        config.strategy, symbol, exchange, timeframe, ds.candles,
    )
    result = run_backtest(ds.frame, strategy, config)
    metrics = compute_metrics(result, risk_free_rate=float(req.get("risk_free_rate", 0.0)))
    logger.info(
        "backtest done: %s trades=%d net=%.2f", config.strategy,
        metrics["total_trades"], metrics["net_profit"],
    )
    return {"result": result, "metrics": metrics, "config": config.snapshot()}

"""Backtest job endpoints.

POST /backtests  -> 202 + {id, status: QUEUED}; runs in background.
GET  /backtests/{id}              -> status
GET  /backtests/{id}/trades       -> trade table (when COMPLETED)
GET  /backtests/{id}/metrics      -> full metric set
GET  /backtests/{id}/equity       -> equity curve series
GET  /backtests/{id}/drawdown     -> drawdown series
GET  /backtests/{id}/monthly-performance -> monthly return map
"""
import logging

from fastapi import APIRouter, BackgroundTasks, HTTPException

from app.analytics.readiness import assess_readiness
from app.backtesting.engine import BacktestResult
from app.schemas.backtest import (
    BacktestCreated, BacktestRequest, BacktestStatusOut,
    EquityPointOut, MetricsOut, TradeOut,
)
from app.services.backtest_service import DataNotFoundError, run_backtest_job
from app.services.jobs import BackgroundTasksRunner, Job, job_store

router = APIRouter(tags=["backtests"])
logger = logging.getLogger(__name__)
runner = BackgroundTasksRunner()


def _get_job(job_id: str) -> Job:
    job = job_store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"backtest {job_id!r} not found")
    return job


def _completed_result(job: Job) -> dict:
    if job.status == "FAILED":
        raise HTTPException(status_code=409, detail=f"backtest failed: {job.error}")
    if job.status != "COMPLETED":
        raise HTTPException(status_code=409, detail=f"backtest is {job.status}, not COMPLETED")
    return job.result  # {"result": BacktestResult, "metrics": {...}, "config": {...}}


@router.post("/backtests", response_model=BacktestCreated, status_code=202)
def create_backtest(req: BacktestRequest, background_tasks: BackgroundTasks) -> BacktestCreated:
    payload = req.model_dump()
    job = runner.submit(background_tasks, "backtest", lambda: run_backtest_job(payload))
    logger.info("backtest queued: %s %s/%s %s", job.id, req.symbol, req.exchange, req.timeframe)
    return BacktestCreated(id=job.id, status=job.status)


@router.get("/backtests/{job_id}", response_model=BacktestStatusOut)
def get_status(job_id: str) -> BacktestStatusOut:
    j = _get_job(job_id)
    return BacktestStatusOut(
        id=j.id, status=j.status, error=j.error,
        created_at=j.created_at.isoformat(),
        started_at=j.started_at.isoformat() if j.started_at else None,
        finished_at=j.finished_at.isoformat() if j.finished_at else None,
    )


@router.get("/backtests/{job_id}/trades", response_model=list[TradeOut])
def get_trades(job_id: str) -> list[TradeOut]:
    bundle = _completed_result(_get_job(job_id))
    result: BacktestResult = bundle["result"]
    return [
        TradeOut(
            trade_seq=t.trade_seq, symbol=t.symbol, strategy=t.strategy, side=t.side.value,
            entry_time=t.entry_time.isoformat(), entry_price=t.entry_price,
            exit_time=t.exit_time.isoformat(), exit_price=t.exit_price,
            quantity=t.quantity, stop_loss=t.stop_loss, take_profit=t.take_profit,
            gross_pnl=t.gross_pnl, brokerage=t.brokerage, slippage_cost=t.slippage_cost,
            other_costs=t.other_costs, net_pnl=t.net_pnl, pnl_pct=t.pnl_pct,
            exit_reason=t.exit_reason.value, holding_seconds=t.holding_seconds,
        )
        for t in result.trades
    ]


@router.get("/backtests/{job_id}/metrics", response_model=MetricsOut)
def get_metrics(job_id: str) -> MetricsOut:
    bundle = _completed_result(_get_job(job_id))
    m = dict(bundle["metrics"])
    # convert OrderedDict period maps to plain dicts for JSON
    for k in ("daily_returns", "weekly_returns", "monthly_returns", "yearly_returns"):
        if k in m:
            m[k] = dict(m[k])
    return MetricsOut(metrics=m)


@router.get("/backtests/{job_id}/equity", response_model=list[EquityPointOut])
def get_equity(job_id: str) -> list[EquityPointOut]:
    bundle = _completed_result(_get_job(job_id))
    return [EquityPointOut(timestamp=p.timestamp.isoformat(), equity=p.equity, drawdown=p.drawdown)
            for p in bundle["result"].equity_curve]


@router.get("/backtests/{job_id}/drawdown", response_model=list[EquityPointOut])
def get_drawdown(job_id: str) -> list[EquityPointOut]:
    bundle = _completed_result(_get_job(job_id))
    return [EquityPointOut(timestamp=p.timestamp.isoformat(), equity=p.equity, drawdown=p.drawdown)
            for p in bundle["result"].equity_curve]


@router.get("/backtests/{job_id}/monthly-performance")
def get_monthly(job_id: str) -> dict:
    bundle = _completed_result(_get_job(job_id))
    return {"monthly_returns": dict(bundle["metrics"]["monthly_returns"])}


@router.get("/backtests/{job_id}/readiness")
def get_readiness(job_id: str) -> dict:
    """Live-trading readiness assessment from the real backtest evidence.

    `oos` query param: pass a completed walk-forward/held-out backtest id to
    include out-of-sample robustness in the assessment.
    """
    bundle = _completed_result(_get_job(job_id))
    result: BacktestResult = bundle["result"]
    metrics = bundle["metrics"]
    cfg = result.config.get("risk", {})
    return assess_readiness(
        metrics, result.trades,
        max_drawdown_limit=cfg.get("max_drawdown_limit"),
    )


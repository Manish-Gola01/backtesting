"""Persist a completed backtest result to the DB (Phase 3 tables).

Optional — only active when DATA_BACKEND=db. Keeps results durable across
restarts and enables history/comparison. In-memory JobStore remains the
fast path for the running process.
"""
from __future__ import annotations

import logging

from app.backtesting.engine import BacktestResult
from app.database.session import get_session_factory
from app.models import (
    Backtest, BacktestEquity, BacktestMetric, BacktestStatus,
    BacktestTrade, Direction, ExitReason, Instrument,
)
from sqlalchemy import select

logger = logging.getLogger(__name__)


def persist_result(job_id: str, bundle: dict, instrument_symbol: str, exchange: str) -> str | None:
    """Write backtest + trades + metrics + equity rows. Returns backtest id."""
    result: BacktestResult = bundle["result"]
    metrics: dict = bundle["metrics"]
    cfg: dict = bundle["config"]
    try:
        sf = get_session_factory()
    except Exception as exc:  # DB not configured -> skip persistence
        logger.warning("persistence skipped (no DB): %s", exc)
        return None

    with sf() as s:
        inst = s.execute(
            select(Instrument).where(Instrument.symbol == instrument_symbol, Instrument.exchange == exchange)
        ).scalar_one_or_none()
        if inst is None:
            logger.warning("persistence skipped: instrument %s/%s not found", instrument_symbol, exchange)
            return None

        bt = Backtest(
            id=job_id,
            strategy_name=cfg["strategy"],
            instrument_id=inst.id,
            timeframe=cfg["timeframe"],
            start_date=result.equity_curve[0].timestamp if result.equity_curve else None,
            end_date=result.equity_curve[-1].timestamp if result.equity_curve else None,
            config=cfg,
            status=BacktestStatus.COMPLETED,
            duration_ms=result.duration_ms,
        )
        s.add(bt)

        for t in result.trades:
            s.add(BacktestTrade(
                backtest_id=job_id, trade_seq=t.trade_seq, symbol=t.symbol, strategy=t.strategy,
                direction=Direction(t.side.value), entry_time=t.entry_time, entry_price=t.entry_price,
                exit_time=t.exit_time, exit_price=t.exit_price, quantity=t.quantity,
                stop_loss=t.stop_loss, take_profit=t.take_profit, gross_pnl=t.gross_pnl,
                brokerage=t.brokerage, slippage_cost=t.slippage_cost, other_costs=t.other_costs,
                net_pnl=t.net_pnl, pnl_pct=t.pnl_pct, exit_reason=ExitReason(t.exit_reason.value),
                holding_seconds=t.holding_seconds,
            ))

        s.add(BacktestMetric(
            backtest_id=job_id,
            net_profit=metrics.get("net_profit"), net_profit_pct=metrics.get("net_profit_pct"),
            total_trades=metrics.get("total_trades"), win_rate=metrics.get("win_rate"),
            profit_factor=None if metrics.get("profit_factor") == float("inf") else metrics.get("profit_factor"),
            max_drawdown=metrics.get("max_drawdown"), max_drawdown_pct=metrics.get("max_drawdown_pct"),
            sharpe_ratio=metrics.get("sharpe_ratio"), sortino_ratio=metrics.get("sortino_ratio"),
            expectancy=metrics.get("expectancy"),
            metrics={k: (dict(v) if hasattr(v, "items") else v) for k, v in metrics.items()},
        ))

        for p in result.equity_curve:
            s.add(BacktestEquity(backtest_id=job_id, timestamp=p.timestamp, equity=p.equity, drawdown=p.drawdown))

        s.commit()
        logger.info("persisted backtest %s (%d trades)", job_id, len(result.trades))
        return job_id

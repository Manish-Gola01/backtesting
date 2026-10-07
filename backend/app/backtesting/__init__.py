"""Backtesting engine: deterministic candle-by-candle event loop.

This package is intentionally free of HTTP and database imports — it is a
pure function of (candles, strategy, config) and is unit-tested for
determinism and the absence of look-ahead bias.
"""
from app.backtesting.config import (
    BacktestConfig,
    CostModel,
    ExecutionModel,
    IntrabarPolicy,
    RiskLimits,
    SizingModel,
    SizingSpec,
)
from app.backtesting.engine import BacktestResult, run_backtest
from app.backtesting.portfolio import Portfolio
from app.backtesting.registry import get_strategy, register_strategy
from app.backtesting.types import EquityPoint, Position, Trade

__all__ = [
    "BacktestConfig",
    "BacktestResult",
    "CostModel",
    "EquityPoint",
    "ExecutionModel",
    "IntrabarPolicy",
    "Portfolio",
    "Position",
    "RiskLimits",
    "SizingModel",
    "SizingSpec",
    "Trade",
    "get_strategy",
    "register_strategy",
    "run_backtest",
]

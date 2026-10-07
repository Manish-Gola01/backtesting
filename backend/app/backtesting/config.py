"""Backtest configuration — the single, immutable spec for one run.

Everything the engine needs lives here; nothing is read from globals or the
environment. A JSON-serializable snapshot of this object is stored per
backtest (Phase 7) → full reproducibility.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Optional


class ExecutionModel(str, Enum):
    NEXT_OPEN = "next_open"      # fill at next candle open (anti-look-ahead default)
    SIGNAL_CLOSE = "signal_close"  # fill at signal candle close (documented aggressive)


class IntrabarPolicy(str, Enum):
    """How to resolve a candle whose range touches BOTH stop-loss and take-profit."""
    CONSERVATIVE = "conservative"          # assume SL first (worst case) — default
    OPTIMISTIC = "optimistic"              # assume TP first (best case)
    LOWER_TIMEFRAME = "lower_timeframe"    # resolve from finer data if provided, else conservative


class SizingModel(str, Enum):
    FIXED_QTY = "fixed_qty"
    FIXED_AMOUNT = "fixed_amount"
    PCT_CAPITAL = "pct_capital"
    RISK_PCT = "risk_pct"        # qty = (equity * risk%) / |entry - stop|


@dataclass(frozen=True)
class SizingSpec:
    model: SizingModel = SizingModel.RISK_PCT
    value: float = 1.0           # qty | $ | % | % — meaning depends on model
    lot_size: Optional[float] = None  # round quantity down to a multiple (None = fractional allowed)
    compounding: bool = True     # size off current equity (True) or initial capital (False)


@dataclass(frozen=True)
class CostModel:
    brokerage_per_trade: float = 0.0   # flat per executed side
    brokerage_pct: float = 0.0         # % of notional per side
    exchange_fee_pct: float = 0.0      # % of notional per side
    other_charges_pct: float = 0.0     # % of notional per side (taxes etc.)
    slippage_pct: float = 0.0          # % price worsening applied each side


@dataclass(frozen=True)
class RiskLimits:
    max_position_size: Optional[float] = None      # absolute qty cap
    max_open_positions: int = 1
    daily_loss_limit: Optional[float] = None       # halt new entries for the day beyond this $ loss
    max_drawdown_limit: Optional[float] = None     # halt new entries beyond this $ drawdown


@dataclass(frozen=True)
class BacktestConfig:
    strategy: str
    symbol: str
    timeframe: str
    initial_capital: float
    params: Mapping[str, Any] = field(default_factory=dict)   # strategy params (validated by strategy)
    sizing: SizingSpec = field(default_factory=SizingSpec)
    costs: CostModel = field(default_factory=CostModel)
    risk: RiskLimits = field(default_factory=RiskLimits)
    execution_model: ExecutionModel = ExecutionModel.NEXT_OPEN
    intrabar_policy: IntrabarPolicy = IntrabarPolicy.CONSERVATIVE
    warmup: int = 0              # candles the strategy needs before it can signal (>= lookback)
    stop_loss_pct: Optional[float] = None    # engine-level default SL/TP when strategy doesn't set levels
    take_profit_pct: Optional[float] = None
    risk_reward: Optional[float] = None      # alternative TP model: TP = entry + R*(entry - SL)

    def snapshot(self) -> dict:
        """JSON-serializable immutable record of this config."""
        def norm(v):
            if isinstance(v, Enum):
                return v.value
            if isinstance(v, Mapping):
                return {k: norm(x) for k, x in v.items()}
            if hasattr(v, "__dataclass_fields__"):
                return {k: norm(getattr(v, k)) for k in v.__dataclass_fields__}
            return v
        return {k: norm(getattr(self, k)) for k in self.__dataclass_fields__}

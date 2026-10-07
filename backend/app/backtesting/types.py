"""Core value types shared across the engine.

`Trade` is the canonical per-trade audit record (spec §11); every field is
populated by the engine and persisted in Phase 7. All money values are plain
floats; costs are always separate from gross P&L (net = gross - costs).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class PositionSide(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"

    @property
    def sign(self) -> int:
        return 1 if self is PositionSide.LONG else -1


class ExitReason(str, Enum):
    STOP_LOSS = "STOP_LOSS"
    TAKE_PROFIT = "TAKE_PROFIT"
    SIGNAL_EXIT = "SIGNAL_EXIT"
    END_OF_DATA = "END_OF_DATA"


@dataclass
class Position:
    """An open position."""
    side: PositionSide
    quantity: float
    entry_price: float          # slippage-adjusted fill
    entry_time: datetime
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    entry_cost: float = 0.0     # brokerage+fees+slippage charged at entry

    def market_value(self, price: float) -> float:
        return self.quantity * price

    def unrealized_pnl(self, price: float) -> float:
        return self.side.sign * self.quantity * (price - self.entry_price)


@dataclass
class Trade:
    """A closed trade — full audit record (spec §11)."""
    trade_seq: int
    symbol: str
    strategy: str
    side: PositionSide
    entry_time: datetime
    entry_price: float
    exit_time: datetime
    exit_price: float
    quantity: float
    stop_loss: Optional[float]
    take_profit: Optional[float]
    gross_pnl: float
    brokerage: float            # total brokerage + fees (entry+exit)
    slippage_cost: float        # total slippage cost (entry+exit)
    other_costs: float
    net_pnl: float
    pnl_pct: float              # net_pnl / (entry notional) * 100
    exit_reason: ExitReason
    holding_seconds: int

    @property
    def total_costs(self) -> float:
        return self.brokerage + self.slippage_cost + self.other_costs


@dataclass
class EquityPoint:
    timestamp: datetime
    equity: float
    drawdown: float = 0.0       # absolute $ below running peak

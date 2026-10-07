"""Strategy plugin contract — the architectural anchor of the strategy layer.

Rules every strategy must obey:

1. The engine (Phase 4) calls :meth:`BaseStrategy.on_candle` once per CLOSED
   candle, passing only data available at that moment: the current candle and
   strictly past candles, ascending, current candle last. A strategy can
   therefore never see the future — look-ahead bias is excluded by
   construction and verified by contract tests (Phase 10).
2. Strategies are pure: no I/O, no globals, no clock access, no randomness
   without an explicit seeded parameter.
3. Returning a signal never executes anything by itself. Execution follows
   the configured execution model (default: next candle open).

Strategies implemented later (e.g. LiquidityOIStrategy in Phase 5,
EMAVWAPStrategy, RSIStrategy) subclass :class:`BaseStrategy` without any
change to the backtesting engine.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Mapping, Optional, Sequence


class SignalType(str, Enum):
    """Actionable output of a strategy for a single closed candle."""

    NONE = "NONE"    # no action
    LONG = "LONG"    # request to open a long position
    SHORT = "SHORT"  # request to open a short position
    EXIT = "EXIT"    # request to close any open position


@dataclass(frozen=True)
class Candle:
    """One OHLCV(+OI) bar. `open_interest=None` means the instrument has no
    OI data — strategies must treat it as unavailable, never as zero."""

    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    open_interest: Optional[float] = None


@dataclass(frozen=True)
class Signal:
    """Strategy output. `reason` is persisted for per-decision auditability.

    `stop_loss` / `take_profit` are optional absolute price levels a strategy
    may suggest (e.g. beyond the sweep wick); when omitted the engine derives
    them from the configured percentage / risk-reward model.
    """

    type: SignalType = SignalType.NONE
    reason: str = ""
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None


class BaseStrategy(ABC):
    """Abstract strategy plugin.

    Class attributes:
        name: unique registry key (e.g. "liquidity_oi").
        description: human-readable summary shown in the UI.
        param_schema: JSON-Schema-ish mapping of parameter name ->
            {type, default, min, max, description}. Drives server-side
            validation now and auto-generated UI forms in Phase 8.
    """

    name: str = "base"
    description: str = ""
    param_schema: Mapping[str, Any] = {}

    @abstractmethod
    def on_candle(
        self,
        candle: Candle,
        history: Sequence[Candle],
        params: Mapping[str, Any],
    ) -> Signal:
        """Evaluate the just-closed `candle` and return a Signal.

        `history` contains only candles with
        `timestamp <= candle.timestamp`, ordered oldest -> newest, and
        includes `candle` as its last element. Implementations MUST NOT
        access any market data outside this argument.
        """

    def validate_params(self, params: Mapping[str, Any]) -> dict[str, Any]:
        """Merge user params over defaults / validate ranges.

        Base implementation passes through; strategies override to enforce
        their `param_schema` (Phase 5).
        """
        return dict(params)

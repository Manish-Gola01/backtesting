"""Strategy plugins. Adding a strategy = one new module + registration (Phase 5)."""

from app.strategies.base import BaseStrategy, Candle, Signal, SignalType
from app.strategies.liquidity_oi import LiquidityOIStrategy

__all__ = ["BaseStrategy", "Candle", "Signal", "SignalType", "LiquidityOIStrategy"]

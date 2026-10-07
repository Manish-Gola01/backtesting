"""Liquidity Sweep + Open Interest strategy.

Implements docs/STRATEGY.md exactly. All parameters configurable; nothing
hard-coded. Receives only past+current candles (anti-look-ahead contract).

Bullish (LONG) at close of candle t:
  level   = min(low[t-N .. t-1])           (strictly prior candles)
  sweep   = low[t]  < level
  reclaim = close[t] > level               (reclaim_mode)
  OI      = delta_oi% >= oi_threshold      (oi_direction / oi_required)
  -> LONG signal; engine fills at next open (execution_model)

Bearish (SHORT) is the exact mirror on prior-N high.
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence

from app.strategies.base import BaseStrategy, Candle, Signal, SignalType


def _pct_change(cur: float, prev: float) -> float | None:
    if prev is None or prev == 0:
        return None
    return (cur - prev) / prev * 100.0


class LiquidityOIStrategy(BaseStrategy):
    name = "liquidity_oi"
    description = (
        "Liquidity sweep of a prior N-candle swing high/low followed by a "
        "reclaim, confirmed by an Open Interest % change over a threshold."
    )
    param_schema: Mapping[str, Any] = {
        "lookback":        {"type": "int",   "default": 20,   "min": 1, "max": 500, "description": "candles used for swing level"},
        "oi_threshold":    {"type": "float", "default": 2.5,  "min": 0.0, "max": 100.0, "description": "OI %% change trigger"},
        "oi_direction":    {"type": "str",   "default": "rising_confirms", "options": ["rising_confirms", "falling_confirms", "either"]},
        "oi_required":     {"type": "bool",  "default": True,  "description": "error if OI data absent when true"},
        "reclaim_mode":    {"type": "str",   "default": "close_above", "options": ["close_above", "close_above_body", "pct_reclaim"]},
        "reclaim_pct":     {"type": "float", "default": 0.0,  "min": 0.0, "description": "%% beyond level for pct_reclaim mode"},
        "sweep_lookahead": {"type": "int",   "default": 1,    "min": 1, "max": 10, "description": "candles between sweep and reclaim"},
    }

    # -- defaults merged over user params ------------------------------------
    _DEFAULTS = {k: v["default"] for k, v in param_schema.items()}

    def validate_params(self, params: Mapping[str, Any]) -> dict[str, Any]:
        p = {**self._DEFAULTS, **dict(params)}
        if int(p["lookback"]) < 1:
            raise ValueError("lookback must be >= 1")
        if p["oi_direction"] not in ("rising_confirms", "falling_confirms", "either"):
            raise ValueError("oi_direction must be rising_confirms|falling_confirms|either")
        if p["reclaim_mode"] not in ("close_above", "close_above_body", "pct_reclaim"):
            raise ValueError("invalid reclaim_mode")
        if int(p["sweep_lookahead"]) < 1:
            raise ValueError("sweep_lookahead must be >= 1")
        p["lookback"] = int(p["lookback"])
        p["sweep_lookahead"] = int(p["sweep_lookahead"])
        p["oi_threshold"] = float(p["oi_threshold"])
        p["reclaim_pct"] = float(p["reclaim_pct"])
        p["oi_required"] = bool(p["oi_required"])
        return p

    # -- helpers --------------------------------------------------------------
    def _oi_ok(self, history: Sequence[Candle], p: Mapping[str, Any]) -> bool:
        """OI confirmation. Returns False when OI missing and required."""
        cur, prev = history[-1].open_interest, history[-2].open_interest
        if cur is None or prev is None:
            return not p["oi_required"]  # missing OI: pass only if not required
        d = _pct_change(cur, prev)
        if d is None:
            return not p["oi_required"]
        thr = p["oi_threshold"]
        dirn = p["oi_direction"]
        if dirn == "either":
            return abs(d) >= thr
        if dirn == "falling_confirms":
            return d <= -thr
        return d >= thr  # rising_confirms

    def _reclaimed(self, candle: Candle, level: float, side: str, p: Mapping[str, Any]) -> bool:
        mode = p["reclaim_mode"]
        if mode == "pct_reclaim":
            band = level * p["reclaim_pct"] / 100.0
            return candle.close > level + band if side == "long" else candle.close < level - band
        if mode == "close_above_body":
            body_top = max(candle.open, candle.close)
            body_bot = min(candle.open, candle.close)
            return body_top > level if side == "long" else body_bot < level
        # close_above (default)
        return candle.close > level if side == "long" else candle.close < level

    # -- main ------------------------------------------------------------------
    def on_candle(self, candle: Candle, history: Sequence[Candle], params: Mapping[str, Any]) -> Signal:
        p = self.validate_params(params)
        n = p["lookback"]
        la = p["sweep_lookahead"]
        if len(history) < n + la:
            return Signal()  # need lookback + sweep_window candles

        # The liquidity level is computed from the `lookback` candles strictly
        # BEFORE the sweep window, so the sweep candles never contaminate the
        # level. Sweep may occur on any of the last `la` candles; the reclaim
        # must occur on the current (last) candle.
        level_window = history[: len(history) - la]      # excludes last `la` candles
        prior = level_window[-(n + 1):]                  # up to n+1, current already excluded
        low_level = min(c.low for c in prior[-n:])
        high_level = max(c.high for c in prior[-n:])

        sweep_window = list(history[-la:])               # ascending; last == current candle

        # ---- bullish: swept the prior low within window, reclaimed now -------
        if any(c.low < low_level for c in sweep_window) and self._reclaimed(candle, low_level, "long", p):
            if self._oi_ok(history, p):
                return Signal(
                    SignalType.LONG,
                    reason=f"sweep+reclaim of {low_level:.2f}; dOI ok",
                    stop_loss=min(c.low for c in sweep_window),
                )

        # ---- bearish: swept the prior high within window, rejected now -------
        if any(c.high > high_level for c in sweep_window) and self._reclaimed(candle, high_level, "short", p):
            if self._oi_ok(history, p):
                return Signal(
                    SignalType.SHORT,
                    reason=f"sweep+reject of {high_level:.2f}; dOI ok",
                    stop_loss=max(c.high for c in sweep_window),
                )

        return Signal()

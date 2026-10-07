"""Risk metrics: max drawdown, Sharpe, Sortino — from the equity curve."""
from __future__ import annotations

import math
from statistics import pstdev
from typing import Optional, Sequence

from app.backtesting.types import EquityPoint

# annualization factors by detected bar spacing (periods per year)
_TRADING_DAYS = 252
_PERIODS = {
    "1m": _TRADING_DAYS * 375, "5m": _TRADING_DAYS * 75, "15m": _TRADING_DAYS * 25,
    "30m": _TRADING_DAYS * 12, "1h": _TRADING_DAYS * 6, "1d": _TRADING_DAYS,
    "1w": 52,
}


def max_drawdown(equity: Sequence[EquityPoint]) -> tuple[float, float]:
    """(max_drawdown_$, max_drawdown_%) from running peak."""
    if not equity:
        return 0.0, 0.0
    peak = equity[0].equity
    mdd = 0.0
    mdd_pct = 0.0
    for pt in equity:
        peak = max(peak, pt.equity)
        dd = peak - pt.equity
        if dd > mdd:
            mdd = dd
            mdd_pct = (dd / peak * 100.0) if peak else 0.0
    return mdd, mdd_pct


def _bar_seconds(equity: Sequence[EquityPoint]) -> Optional[float]:
    if len(equity) < 2:
        return None
    deltas = [
        (equity[i + 1].timestamp - equity[i].timestamp).total_seconds()
        for i in range(len(equity) - 1)
    ]
    deltas = [d for d in deltas if d > 0]
    return min(deltas) if deltas else None


def _periodic_returns(equity: Sequence[EquityPoint]) -> list[float]:
    rets = []
    for i in range(1, len(equity)):
        a, b = equity[i - 1].equity, equity[i].equity
        if a:
            rets.append((b - a) / a)
    return rets


def _annualization(equity: Sequence[EquityPoint]) -> float:
    sec = _bar_seconds(equity)
    if not sec:
        return 1.0
    bars_per_day = 86400 / sec
    return math.sqrt(_TRADING_DAYS * bars_per_day)


def sharpe_ratio(equity: Sequence[EquityPoint], risk_free_rate: float = 0.0) -> Optional[float]:
    """Annualized Sharpe from per-bar returns. None if insufficient/variance=0.

    risk_free_rate is an ANNUAL rate in % (e.g. 5.0 = 5%/yr), converted per-bar.
    """
    rets = _periodic_returns(equity)
    if len(rets) < 2:
        return None
    ann = _annualization(equity)
    rf_per_bar = (risk_free_rate / 100.0) / (ann ** 2)
    excess = [r - rf_per_bar for r in rets]
    sd = pstdev(excess)
    if sd == 0:
        return None
    mean = sum(excess) / len(excess)
    return (mean / sd) * ann


def sortino_ratio(equity: Sequence[EquityPoint], risk_free_rate: float = 0.0) -> Optional[float]:
    """Annualized Sortino — downside deviation only. None if no downside moves."""
    rets = _periodic_returns(equity)
    if len(rets) < 2:
        return None
    ann = _annualization(equity)
    rf_per_bar = (risk_free_rate / 100.0) / (ann ** 2)
    excess = [r - rf_per_bar for r in rets]
    mean = sum(excess) / len(excess)
    downside = [r for r in excess if r < 0]
    if not downside:
        return None
    dd = math.sqrt(sum(r * r for r in downside) / len(downside))
    if dd == 0:
        return None
    return (mean / dd) * ann

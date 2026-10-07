"""Position sizing models (spec §8). All configurable; fractional allowed unless lot_size set."""
from __future__ import annotations

from typing import Optional

from app.backtesting.config import SizingModel, SizingSpec


def compute_quantity(
    spec: SizingSpec,
    *,
    equity: float,
    initial_capital: float,
    entry_price: float,
    stop_loss: Optional[float],
    max_position_size: Optional[float] = None,
) -> float:
    """Return the order quantity for a new position.

    risk_pct: qty = (risk_capital * value%) / |entry - stop|. Falls back to
    pct_capital semantics if no stop is available (documented).
    """
    capital_base = equity if spec.compounding else initial_capital

    if spec.model is SizingModel.FIXED_QTY:
        qty = spec.value
    elif spec.model is SizingModel.FIXED_AMOUNT:
        qty = spec.value / entry_price
    elif spec.model is SizingModel.PCT_CAPITAL:
        qty = (capital_base * spec.value / 100.0) / entry_price
    elif spec.model is SizingModel.RISK_PCT:
        risk_amount = capital_base * spec.value / 100.0
        if stop_loss is not None and stop_loss != entry_price:
            per_unit_risk = abs(entry_price - stop_loss)
            qty = risk_amount / per_unit_risk
        else:  # no stop defined -> fall back to deploying value% of capital
            qty = risk_amount / entry_price
    else:  # pragma: no cover - guarded by enum
        raise ValueError(f"unknown sizing model {spec.model}")

    if spec.lot_size and spec.lot_size > 0:
        qty = (qty // spec.lot_size) * spec.lot_size
    if max_position_size is not None:
        qty = min(qty, max_position_size)
    return max(qty, 0.0)

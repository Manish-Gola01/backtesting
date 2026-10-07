"""Execution & cost model.

Fill price rules (no look-ahead):
- NEXT_OPEN:   fill at next candle's open, worsened by slippage.
- SIGNAL_CLOSE: fill at the signal candle's close (aggressive; documented).

Slippage always hurts: LONG pays more / receives less; SHORT the reverse.
Costs are computed per side and tracked separately from gross P&L.
"""
from __future__ import annotations

from app.backtesting.config import CostModel
from app.backtesting.types import PositionSide


def apply_slippage(price: float, side: PositionSide, *, is_entry: bool, slippage_pct: float) -> float:
    """Return the fill price worsened by slippage for this side/action.

    BUY (long entry / short exit): price * (1 + s)
    SELL (long exit / short entry): price * (1 - s)
    """
    s = slippage_pct / 100.0
    buying = (side is PositionSide.LONG) == is_entry
    return price * (1 + s) if buying else price * (1 - s)


def slippage_cost(notional: float, slippage_pct: float) -> float:
    return notional * slippage_pct / 100.0


def side_charges(notional: float, costs: CostModel) -> dict[str, float]:
    """Brokerage/fees/other for ONE executed side (entry or exit)."""
    brokerage = costs.brokerage_per_trade + notional * costs.brokerage_pct / 100.0
    exchange = notional * costs.exchange_fee_pct / 100.0
    other = notional * costs.other_charges_pct / 100.0
    return {"brokerage": brokerage, "exchange": exchange, "other": other}

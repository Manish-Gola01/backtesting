"""Period returns (daily/weekly/monthly/yearly) from the equity curve."""
from __future__ import annotations

from collections import OrderedDict
from typing import Sequence

from app.backtesting.types import EquityPoint


def _group_key(ts, freq: str) -> str:
    if freq == "daily":
        return ts.strftime("%Y-%m-%d")
    if freq == "weekly":
        y, w, _ = ts.isocalendar()
        return f"{y}-W{w:02d}"
    if freq == "monthly":
        return ts.strftime("%Y-%m")
    if freq == "yearly":
        return ts.strftime("%Y")
    raise ValueError(f"unknown freq {freq}")


def period_returns(equity: Sequence[EquityPoint], freq: str) -> "OrderedDict[str, float]":
    """Return % change per period, chronological. First period measured from
    the first equity point's value as the base.

    Formula per period: (last_equity - first_equity) / first_equity * 100,
    where first_equity is the period's opening equity (prior period's close).
    """
    out: "OrderedDict[str, float]" = OrderedDict()
    if not equity:
        return out
    # build ordered (period -> [equities])
    groups: "OrderedDict[str, list[float]]" = OrderedDict()
    for pt in equity:
        groups.setdefault(_group_key(pt.timestamp, freq), []).append(pt.equity)
    prev_close = None
    for key, vals in groups.items():
        start = prev_close if prev_close is not None else vals[0]
        end = vals[-1]
        out[key] = ((end - start) / start * 100.0) if start else 0.0
        prev_close = end
    return out

"""Strict validation of parsed market data — all rule checks in one pass.

Every failure is collected and reported; a dataset is only returned when it
passes every enabled rule. Nothing is silently repaired or fabricated.

Rules (mapped to project spec §18):
  required columns / schema   → enforced in loader.py
  timestamp format + tz-aware → enforced in loader.py
  R1 duplicate timestamps     → error
  R2 missing candles (gaps)   → warning by default, error when require_contiguous
  R3 invalid OHLC relations   → high < low / high < max(o,c) / low > min(o,c)
  R4 negative volume          → error
  R5 missing OI               → never fabricated; has_oi=False (or error if OI required)
  R6 incorrect sorting        → error (engine requires strict ascending input)
  R7 non-positive prices      → error (o/h/l/c must be > 0)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

from app.data.errors import DataValidationError
from app.data.schemas import DataSetMeta, ParsedDataSet
from app.utils.timeframes import is_valid_timeframe, timeframe_seconds

# Market data has legitimate session gaps (overnight/weekends); a gap larger
# than this multiple of the expected bar spacing is considered a real hole.
_GAP_TOLERANCE_MULTIPLE = 5


@dataclass
class ValidationReport:
    issues: list[str] = field(default_factory=list)
    row_errors: dict[int, list[str]] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.issues and not self.row_errors

    def add(self, msg: str) -> None:
        self.issues.append(msg)

    def add_row(self, row: int, msg: str) -> None:
        self.row_errors.setdefault(row, []).append(msg)


def validate_frame(
    frame: pd.DataFrame,
    *,
    symbol: str,
    exchange: str,
    timeframe: str,
    require_oi: bool = False,
    require_contiguous: bool = False,
    max_gap_multiple: int = _GAP_TOLERANCE_MULTIPLE,
    preexisting_row_errors: Optional[dict[int, list[str]]] = None,
) -> ParsedDataSet:
    """Validate a parsed frame; return a canonical ParsedDataSet or raise.

    Raises DataValidationError listing EVERY violation found.
    """
    rep = ValidationReport()
    if preexisting_row_errors:
        for row, msgs in preexisting_row_errors.items():
            for m in msgs:
                rep.add_row(row, m)

    if not symbol or not symbol.strip():
        rep.add("symbol is required")
    if not exchange or not exchange.strip():
        rep.add("exchange is required")
    if not is_valid_timeframe(timeframe):
        rep.add(f"invalid timeframe: {timeframe!r}")

    if frame.empty:
        rep.add("dataset contains no rows")
        raise DataValidationError(rep.issues, rep.row_errors)

    ts = frame["timestamp"]

    # --- R6: sorting -------------------------------------------------------
    if not ts.is_monotonic_increasing:
        first_bad = int(np.argmax((ts.diff().dt.total_seconds() < 0).to_numpy()))
        rep.add(
            f"rows are not sorted ascending by timestamp "
            f"(first out-of-order near data row {first_bad + 2}); "
            f"sort the file before uploading"
        )

    # --- R1: duplicate timestamps ------------------------------------------
    dup_mask = ts.duplicated(keep=False)
    if dup_mask.any():
        idx = np.where(dup_mask.to_numpy())[0]
        sample = [int(i) + 2 for i in idx[:10]]
        rep.add(
            f"{int(dup_mask.sum())} duplicate timestamp row(s) "
            f"(CSV rows e.g. {sample}); each timestamp must appear at most once"
        )

    # --- R7: non-positive / missing prices ---------------------------------
    for col in ("open", "high", "low", "close"):
        series = frame[col]
        bad = series.isna() | (series <= 0)
        if bad.any():
            for i in np.where(bad.to_numpy())[0][:20]:
                val = series.iloc[i]
                rep.add_row(
                    int(i) + 2,
                    f"invalid {col}: {'missing' if pd.isna(val) else val} (must be > 0)",
                )

    # --- R3: OHLC internal consistency -------------------------------------
    o, h, l_, c = frame["open"], frame["high"], frame["low"], frame["close"]
    valid = o.notna() & h.notna() & l_.notna() & c.notna()
    bad_hl = valid & (h < l_)
    bad_h = valid & (h < np.maximum(o, c))
    bad_l = valid & (l_ > np.minimum(o, c))
    for mask, msg in (
        (bad_hl, "high < low"),
        (bad_h, "high is below open or close"),
        (bad_l, "low is above open or close"),
    ):
        if mask.any():
            for i in np.where(mask.to_numpy())[0][:20]:
                rep.add_row(int(i) + 2, f"invalid OHLC: {msg}")

    # --- R4: negative / missing volume --------------------------------------
    v = frame["volume"]
    bad_v = v.isna() | (v < 0)
    if bad_v.any():
        for i in np.where(bad_v.to_numpy())[0][:20]:
            val = v.iloc[i]
            rep.add_row(
                int(i) + 2,
                f"invalid volume: {'missing' if pd.isna(val) else val} (must be >= 0)",
            )

    # --- R5: open interest ---------------------------------------------------
    oi = frame["open_interest"]
    has_oi = bool(oi.notna().any())
    if require_oi and not has_oi:
        rep.add(
            "open_interest data is required for this strategy/instrument but the "
            "file contains none; OI values are never fabricated — upload data "
            "that includes an open_interest column"
        )
    elif has_oi:
        bad_oi = oi.notna() & (oi < 0)
        if bad_oi.any():
            for i in np.where(bad_oi.to_numpy())[0][:20]:
                rep.add_row(int(i) + 2, f"negative open_interest: {oi.iloc[i]}")

    # --- R2: missing candles -------------------------------------------------
    gap_warnings: list[str] = []
    if is_valid_timeframe(timeframe) and len(frame) > 1:
        step = timeframe_seconds(timeframe)
        deltas = ts.diff().dt.total_seconds().dropna()
        # ignore duplicates (0s) when checking gaps; already reported above
        positive = deltas[deltas > 0]
        holes = positive[positive > step * max_gap_multiple]
        if len(holes):
            worst_ts = ts.iloc[int(positive[positive > step * max_gap_multiple].index[0])]
            msg = (
                f"{len(holes)} gap(s) larger than {max_gap_multiple}x the expected "
                f"{timeframe} spacing detected (first before {worst_ts.isoformat()}); "
                f"largest gap = {int(holes.max())}s vs expected {step}s"
            )
            (rep.add if require_contiguous else gap_warnings.append)(msg)

    if not rep.ok:
        raise DataValidationError(rep.issues, rep.row_errors)

    clean = frame.sort_values("timestamp").reset_index(drop=True)
    meta = DataSetMeta(
        symbol=symbol.strip().upper(),
        exchange=exchange.strip().upper(),
        timeframe=timeframe,
        has_oi=has_oi,
        start=clean["timestamp"].iloc[0],
        end=clean["timestamp"].iloc[-1],
    )
    ds = ParsedDataSet(meta=meta, frame=clean)
    # surface warnings through the object without failing validation
    object.__setattr__(ds, "warnings", gap_warnings)
    return ds

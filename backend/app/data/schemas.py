"""Validated dataset container — the data layer's interchange format.

A `ParsedDataSet` is produced by the CSV loader + validator and consumed by:
- the repository (Phase 2 in-memory, Phase 3 PostgreSQL persistence)
- the backtesting engine (Phase 4)

The dataframe always has these columns, in ascending timestamp order, with a
UTC tz-aware `timestamp`: open, high, low, close, volume, open_interest.
`open_interest` is all-NaN for OHLCV-only instruments (never fabricated).
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

CANONICAL_COLUMNS = [
    "timestamp",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "open_interest",
]


@dataclass(frozen=True)
class DataSetMeta:
    symbol: str
    exchange: str
    timeframe: str
    has_oi: bool
    start: pd.Timestamp
    end: pd.Timestamp


@dataclass(frozen=True)
class ParsedDataSet:
    meta: DataSetMeta
    frame: pd.DataFrame  # CANONICAL_COLUMNS, ascending unique timestamps

    @property
    def candles(self) -> int:
        return len(self.frame)

    def summary(self) -> dict:
        return {
            "symbol": self.meta.symbol,
            "exchange": self.meta.exchange,
            "timeframe": self.meta.timeframe,
            "has_oi": self.meta.has_oi,
            "candles": self.candles,
            "start": self.meta.start.isoformat(),
            "end": self.meta.end.isoformat(),
        }

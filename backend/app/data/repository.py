"""Data repository — Phase 2 in-memory implementation.

Phase 3 swaps this for PostgreSQL behind the same interface; callers (API,
services, engine) are unaffected. Keyed by (symbol, exchange, timeframe);
re-upload of the same key is rejected unless `overwrite=True` — duplicate
candles can never accumulate.
"""
from __future__ import annotations

from threading import Lock
from typing import Optional

from app.data.errors import DataValidationError
from app.data.schemas import ParsedDataSet


class InMemoryDataStore:
    def __init__(self) -> None:
        self._lock = Lock()
        self._datasets: dict[tuple[str, str, str], ParsedDataSet] = {}

    @staticmethod
    def _key(ds: ParsedDataSet) -> tuple[str, str, str]:
        m = ds.meta
        return (m.symbol, m.exchange, m.timeframe)

    def save(self, ds: ParsedDataSet, *, overwrite: bool = False) -> None:
        key = self._key(ds)
        with self._lock:
            if key in self._datasets and not overwrite:
                raise DataValidationError(
                    [
                        f"dataset {key[0]}/{key[1]} {key[2]} already exists "
                        f"({self._datasets[key].candles} candles); "
                        f"pass overwrite=true to replace it"
                    ]
                )
            self._datasets[key] = ds

    def get(self, symbol: str, exchange: str, timeframe: str) -> Optional[ParsedDataSet]:
        return self._datasets.get((symbol.upper(), exchange.upper(), timeframe))

    def coverage(self) -> list[dict]:
        return [ds.summary() for ds in self._datasets.values()]

    def clear(self) -> None:
        with self._lock:
            self._datasets.clear()


# Process-wide store, replaced by a DB-backed repository in Phase 3.
store = InMemoryDataStore()

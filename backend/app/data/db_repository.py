"""SQLAlchemy-backed data repository — the Phase 3 production store.

Implements the same interface as InMemoryDataStore (save / get / coverage /
clear) so the API and engine are unaffected by the swap. Duplicate candles are
impossible: historical_data's composite PK rejects them at the DB level.
"""
from __future__ import annotations

from threading import Lock
from typing import Optional

import pandas as pd
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session, sessionmaker

from app.data.errors import DataValidationError
from app.data.schemas import CANONICAL_COLUMNS, DataSetMeta, ParsedDataSet
from app.models import HistoricalData, Instrument, InstrumentType


class SqlAlchemyDataStore:
    def __init__(self, session_factory: sessionmaker[Session], default_type: InstrumentType = InstrumentType.INDEX):
        self._sf = session_factory
        self._default_type = default_type
        self._lock = Lock()

    # --- instrument resolution -------------------------------------------
    def _get_or_create_instrument(self, s: Session, meta: DataSetMeta) -> Instrument:
        stmt = select(Instrument).where(
            Instrument.symbol == meta.symbol,
            Instrument.exchange == meta.exchange,
        )
        inst = s.execute(stmt).scalar_one_or_none()
        if inst is None:
            inst = Instrument(
                symbol=meta.symbol,
                exchange=meta.exchange,
                instrument_type=self._default_type,
                has_oi=meta.has_oi,
            )
            s.add(inst)
            s.flush()  # assign PK
        elif meta.has_oi and not inst.has_oi:
            inst.has_oi = True  # upgrade flag when OI data arrives
        return inst

    # --- interface ---------------------------------------------------------
    def save(self, ds: ParsedDataSet, *, overwrite: bool = False) -> None:
        with self._lock, self._sf() as s:
            inst = self._get_or_create_instrument(s, ds.meta)

            existing = s.execute(
                select(HistoricalData.instrument_id).where(
                    HistoricalData.instrument_id == inst.id,
                    HistoricalData.timeframe == ds.meta.timeframe,
                ).limit(1)
            ).first()
            if existing and not overwrite:
                raise DataValidationError(
                    [
                        f"dataset {ds.meta.symbol}/{ds.meta.exchange} {ds.meta.timeframe} "
                        f"already exists; pass overwrite=true to replace it"
                    ]
                )
            if existing and overwrite:
                s.execute(
                    delete(HistoricalData).where(
                        HistoricalData.instrument_id == inst.id,
                        HistoricalData.timeframe == ds.meta.timeframe,
                    )
                )

            rows = [
                {
                    "instrument_id": inst.id,
                    "timeframe": ds.meta.timeframe,
                    "timestamp": ts.to_pydatetime(),
                    "open": float(r.open),
                    "high": float(r.high),
                    "low": float(r.low),
                    "close": float(r.close),
                    "volume": float(r.volume),
                    "open_interest": (None if pd.isna(r.open_interest) else float(r.open_interest)),
                }
                for ts, r in ds.frame.set_index("timestamp").iterrows()
            ]
            # Composite-PK-safe bulk upsert: dialect-correct "do nothing on
            # conflict" so a re-upload never creates duplicate candles.
            dialect = s.bind.dialect.name if s.bind else "sqlite"
            if dialect == "postgresql":
                stmt = pg_insert(HistoricalData).values(rows)
                stmt = stmt.on_conflict_do_nothing(
                    index_elements=["instrument_id", "timeframe", "timestamp"]
                )
                s.execute(stmt)
            else:  # sqlite (local verification)
                stmt = sqlite_insert(HistoricalData).values(rows)
                stmt = stmt.on_conflict_do_nothing(
                    index_elements=["instrument_id", "timeframe", "timestamp"]
                )
                s.execute(stmt)
            s.commit()

    def get(self, symbol: str, exchange: str, timeframe: str) -> Optional[ParsedDataSet]:
        with self._sf() as s:
            inst = s.execute(
                select(Instrument).where(
                    Instrument.symbol == symbol.upper(),
                    Instrument.exchange == exchange.upper(),
                )
            ).scalar_one_or_none()
            if inst is None:
                return None
            rows = s.execute(
                select(HistoricalData).where(
                    HistoricalData.instrument_id == inst.id,
                    HistoricalData.timeframe == timeframe,
                ).order_by(HistoricalData.timestamp.asc())
            ).scalars().all()
            if not rows:
                return None
            frame = pd.DataFrame(
                [
                    {
                        "timestamp": pd.Timestamp(r.timestamp),
                        "open": r.open, "high": r.high, "low": r.low, "close": r.close,
                        "volume": r.volume, "open_interest": r.open_interest,
                    }
                    for r in rows
                ]
            )[CANONICAL_COLUMNS]
            meta = DataSetMeta(
                symbol=inst.symbol, exchange=inst.exchange, timeframe=timeframe,
                has_oi=bool(frame["open_interest"].notna().any()),
                start=frame["timestamp"].iloc[0], end=frame["timestamp"].iloc[-1],
            )
            return ParsedDataSet(meta=meta, frame=frame)

    def coverage(self) -> list[dict]:
        with self._sf() as s:
            out = []
            for inst in s.execute(select(Instrument)).scalars().all():
                tfs = s.execute(
                    select(HistoricalData.timeframe).where(
                        HistoricalData.instrument_id == inst.id
                    ).distinct()
                ).scalars().all()
                for tf in tfs:
                    ds = self.get(inst.symbol, inst.exchange, tf)
                    if ds is not None:
                        out.append(ds.summary())
            return out

    def clear(self) -> None:
        with self._lock, self._sf() as s:
            for tbl in (HistoricalData, Instrument):
                s.execute(delete(tbl))
            s.commit()

"""Unit + integration tests for the Phase 3 database layer (verified on SQLite)."""
import io
from pathlib import Path

import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.data import parse_csv, validate_frame
from app.data.db_repository import SqlAlchemyDataStore
from app.data.errors import DataValidationError
from app.database.session import Base, make_engine, make_session_factory
from app.models import HistoricalData, Instrument

FIXTURES = Path(__file__).parent / "fixtures"
COMMON = dict(symbol="SENSEX", exchange="BSE", timeframe="1m")


@pytest.fixture()
def db_store(tmp_path, monkeypatch):
    """Fresh SQLite DB per test, schema created from metadata."""
    db_file = tmp_path / "test.db"
    engine = make_engine(f"sqlite:///{db_file}")
    Base.metadata.create_all(engine)
    sf = make_session_factory(engine)
    yield SqlAlchemyDataStore(sf)
    engine.dispose()


def _ds(name="valid_1m.csv", **kw):
    with open(FIXTURES / name, "rb") as fh:
        frame, errors = parse_csv(fh, source_name=name)
    return validate_frame(frame, **{**COMMON, **kw})


def test_schema_has_all_8_tables(db_store):
    tables = set(Base.metadata.tables)
    assert {
        "users", "instruments", "strategies", "historical_data",
        "backtests", "backtest_trades", "backtest_metrics", "backtest_equity",
    } <= tables


def test_save_and_get_roundtrip(db_store):
    ds = _ds()
    db_store.save(ds)
    got = db_store.get("SENSEX", "BSE", "1m")
    assert got is not None
    assert got.candles == ds.candles == 10
    assert got.meta.has_oi is True
    assert list(got.frame["close"]) == list(ds.frame["close"])
    # open interest preserved
    assert got.frame["open_interest"].notna().all()


def test_duplicate_candles_impossible(db_store):
    ds = _ds()
    db_store.save(ds)
    # re-saving same key without overwrite -> error
    with pytest.raises(DataValidationError):
        db_store.save(ds)
    # but even a raw re-insert of overlapping rows can't create dup PKs
    db_store.save(ds, overwrite=True)
    assert db_store.get("SENSEX", "BSE", "1m").candles == 10


def test_oi_absent_stored_as_null(db_store):
    ds = _ds("valid_no_oi.csv", timeframe="5m")
    db_store.save(ds)
    got = db_store.get("SENSEX", "BSE", "5m")
    assert got.meta.has_oi is False
    assert got.frame["open_interest"].isna().all()  # NULL, never fabricated


def test_instrument_flag_upgraded_when_oi_arrives(db_store):
    db_store.save(_ds("valid_no_oi.csv", timeframe="5m"))
    db_store.save(_ds("valid_1m.csv", timeframe="1m"))
    with db_store._sf() as s:
        inst = s.execute(select(Instrument).where(Instrument.symbol == "SENSEX")).scalar_one()
        assert inst.has_oi is True  # upgraded by the OI-bearing upload


def test_coverage_lists_each_timeframe(db_store):
    db_store.save(_ds("valid_1m.csv", timeframe="1m"))
    db_store.save(_ds("valid_no_oi.csv", timeframe="5m"))
    cov = db_store.coverage()
    assert {f"{c['symbol']}/{c['timeframe']}" for c in cov} == {"SENSEX/1m", "SENSEX/5m"}


def test_clear_empties_store(db_store):
    db_store.save(_ds())
    db_store.clear()
    assert db_store.coverage() == []
    assert db_store.get("SENSEX", "BSE", "1m") is None

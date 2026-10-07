"""Unit tests for CSV parsing + validation (spec §18)."""
import io
from pathlib import Path

import pytest

from app.data import (
    DataValidationError,
    UnsupportedSchemaError,
    parse_csv,
    validate_frame,
)

FIXTURES = Path(__file__).parent / "fixtures"

COMMON = dict(symbol="sensex", exchange="bse", timeframe="1m")


def _load(name: str):
    with open(FIXTURES / name, "rb") as fh:
        return parse_csv(fh, source_name=name)


# ---------------------------------------------------------------- schema ---

def test_missing_required_column_rejected():
    csv = b"timestamp,open,high,low,close\n2024-01-01T09:15:00+00:00,1,2,0.5,1.5\n"
    with pytest.raises(UnsupportedSchemaError) as ei:
        parse_csv(io.BytesIO(csv))
    assert any("volume" in msg for msg in ei.value.issues)


def test_column_aliases_accepted():
    csv = (
        b"Date,O,H,L,C,Vol,OI\n"
        b"2024-01-01T09:15:00+00:00,100,101,99,100.5,1000,5000\n"
        b"2024-01-01T09:16:00+00:00,100.5,101.5,100,101,900,5100\n"
    )
    frame, errors = parse_csv(io.BytesIO(csv))
    assert not errors
    ds = validate_frame(frame, **COMMON)
    assert ds.candles == 2
    assert ds.meta.has_oi


def test_unparsable_timestamp_reported_per_row():
    # fixture mixes: naive timestamps (dropped, not row-errors) + one garbage
    # string (dropped, reported as row error). Only the valid tz-aware row survives.
    frame, errors = _load("bad_timestamp.csv")
    assert errors  # the 'not-a-timestamp' row is reported
    assert any(3 == row for row in errors)
    with pytest.raises(DataValidationError) as ei:
        validate_frame(frame, **COMMON, preexisting_row_errors=errors)
    assert ei.value.row_errors  # surfaces the reported row


def test_naive_timestamps_rejected():
    csv = (
        b"timestamp,open,high,low,close,volume\n"
        b"2024-01-01 09:15:00,100,101,99,100.5,1000\n"
        b"2024-01-01 09:16:00,100.5,101.5,100,101,900\n"
    )
    frame, errors = parse_csv(io.BytesIO(csv))
    with pytest.raises(DataValidationError):
        validate_frame(frame, **COMMON, preexisting_row_errors=errors)


# ------------------------------------------------------------- validity ---

def test_valid_file_with_oi_passes():
    frame, errors = _load("valid_1m.csv")
    ds = validate_frame(frame, **COMMON, preexisting_row_errors=errors)
    assert ds.candles == 10
    assert ds.meta.has_oi
    assert ds.meta.symbol == "SENSEX"  # upper-cased
    assert ds.frame["timestamp"].is_monotonic_increasing
    assert str(ds.frame["timestamp"].dt.tz) != "None"  # tz-aware


def test_valid_file_without_oi_passes_and_flags_has_oi_false():
    frame, errors = _load("valid_no_oi.csv")
    ds = validate_frame(frame, **COMMON)
    assert ds.candles == 5
    assert ds.meta.has_oi is False
    assert ds.frame["open_interest"].isna().all()  # NaN = "no data"


def test_missing_oi_rejected_when_strategy_requires_it():
    frame, errors = _load("valid_no_oi.csv")
    with pytest.raises(DataValidationError) as ei:
        validate_frame(frame, **COMMON, require_oi=True)
    assert any("never fabricated" in msg for msg in ei.value.issues)


def test_duplicate_timestamps_rejected():
    frame, errors = _load("duplicate_timestamps.csv")
    with pytest.raises(DataValidationError) as ei:
        validate_frame(frame, **COMMON)
    assert any("duplicate timestamp" in msg for msg in ei.value.issues)


def test_unsorted_rows_rejected():
    frame, errors = _load("unsorted.csv")
    with pytest.raises(DataValidationError) as ei:
        validate_frame(frame, **COMMON)
    assert any("not sorted" in msg for msg in ei.value.issues)


def test_bad_ohlc_relationships_rejected():
    frame, errors = _load("bad_ohlc.csv")
    with pytest.raises(DataValidationError) as ei:
        validate_frame(frame, **COMMON)
    assert ei.value.row_errors  # row-level OHLC violations


def test_negative_volume_rejected():
    frame, errors = _load("negative_volume.csv")
    with pytest.raises(DataValidationError) as ei:
        validate_frame(frame, **COMMON)
    assert any("volume" in m for msgs in ei.value.row_errors.values() for m in msgs)


def test_nonpositive_prices_rejected():
    csv = (
        b"timestamp,open,high,low,close,volume\n"
        b"2024-01-01T09:15:00+00:00,0,101,99,100.5,1000\n"
        b"2024-01-01T09:16:00+00:00,100.5,101.5,100,101,900\n"
    )
    frame, errors = parse_csv(io.BytesIO(csv))
    with pytest.raises(DataValidationError):
        validate_frame(frame, **COMMON, preexisting_row_errors=errors)


# ------------------------------------------------------------------ gaps ---

def test_large_gap_warns_by_default_but_passes():
    frame, errors = _load("missing_candles.csv")
    ds = validate_frame(frame, **COMMON)
    assert ds.candles == 4
    assert getattr(ds, "warnings")  # gap surfaced as warning


def test_large_gap_fails_when_contiguous_required():
    frame, errors = _load("missing_candles.csv")
    with pytest.raises(DataValidationError) as ei:
        validate_frame(frame, **COMMON, require_contiguous=True)
    assert any("gap" in msg.lower() for msg in ei.value.issues)


def test_invalid_timeframe_rejected():
    frame, errors = _load("valid_no_oi.csv")
    with pytest.raises(DataValidationError):
        validate_frame(frame, symbol="X", exchange="Y", timeframe="7x")

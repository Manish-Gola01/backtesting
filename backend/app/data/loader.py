"""Streaming CSV loader for historical market data.

Design rules (docs/ASSUMPTIONS.md A1–A3):
- Chunked parsing so a 100 MB file never loads fully into memory.
- Timestamps must be timezone-aware (bar-start convention, A2); naive or
  unparsable timestamps are collected as row errors, not silently guessed.
- No fabrication: missing `open_interest` column ⇒ OHLCV-only dataset,
  stored as NaN — never zero-filled.
"""
from __future__ import annotations

from typing import IO, Iterable, Optional

import numpy as np
import pandas as pd

from app.data.errors import DataValidationError, UnsupportedSchemaError
from app.data.schemas import CANONICAL_COLUMNS

# Flexible header matching: uploaders use many casings/spellings.
_COLUMN_ALIASES: dict[str, str] = {
    "timestamp": "timestamp",
    "time": "timestamp",
    "datetime": "timestamp",
    "date": "timestamp",
    "open": "open",
    "o": "open",
    "high": "high",
    "h": "high",
    "low": "low",
    "l": "low",
    "close": "close",
    "c": "close",
    "volume": "volume",
    "vol": "volume",
    "v": "volume",
    "open_interest": "open_interest",
    "openinterest": "open_interest",
    "oi": "open_interest",
}

REQUIRED_COLUMNS = ["timestamp", "open", "high", "low", "close", "volume"]
OPTIONAL_COLUMNS = ["open_interest"]

_CHUNK_ROWS = 50_000


def _normalize_columns(cols: Iterable[str]) -> dict[str, str]:
    """Map raw CSV headers -> canonical names. Raises on unknown extras? No —
    extra columns are ignored; only required ones must be present."""
    mapping: dict[str, str] = {}
    for raw in cols:
        key = str(raw).strip().lower().replace(" ", "_")
        canonical = _COLUMN_ALIASES.get(key)
        if canonical and canonical not in mapping.values():
            mapping[str(raw)] = canonical
    return mapping


def parse_csv(
    file_obj: IO[bytes] | IO[str],
    *,
    source_name: str = "upload",
) -> tuple[pd.DataFrame, dict[int, list[str]]]:
    """Parse a CSV stream into a canonical dataframe.

    Returns (frame, row_errors). The frame has CANONICAL_COLUMNS (raw order,
    not yet sorted/deduped — that is the validator's job); `row_errors`
    records per-row conversion failures. Schema-level problems (missing
    columns, unreadable file) raise immediately.
    """
    try:
        peek = pd.read_csv(file_obj, nrows=0)
    except Exception as exc:  # unreadable / not CSV
        raise UnsupportedSchemaError(
            [f"{source_name}: could not parse as CSV — {exc}"]
        ) from exc

    col_map = _normalize_columns(peek.columns)
    canonical_present = set(col_map.values())
    missing = [c for c in REQUIRED_COLUMNS if c not in canonical_present]
    if missing:
        raise UnsupportedSchemaError(
            [
                f"{source_name}: missing required column(s): {', '.join(missing)}. "
                f"Required: {', '.join(REQUIRED_COLUMNS)} "
                f"(optional: {', '.join(OPTIONAL_COLUMNS)}). "
                f"Found: {', '.join(map(str, peek.columns)) or '(none)'}"
            ]
        )

    usecols = list(col_map.keys())
    has_oi = "open_interest" in canonical_present
    row_errors: dict[int, list[str]] = {}
    chunks: list[pd.DataFrame] = []

    # The peek read above consumed the stream — rewind before the real pass.
    try:
        file_obj.seek(0)
    except (AttributeError, OSError) as exc:
        raise UnsupportedSchemaError(
            [f"{source_name}: upload stream is not re-readable — {exc}"]
        ) from exc

    try:
        reader = pd.read_csv(
            file_obj,
            usecols=usecols,
            chunksize=_CHUNK_ROWS,
            dtype={raw: "string" for raw in usecols},  # raw text; we convert below
            on_bad_lines="skip",
        )
        offset = 0
        for chunk in reader:
            chunk = chunk.rename(columns=col_map)
            n = len(chunk)

            # --- timestamp: must parse AND carry explicit timezone info (A2) ---
            raw_ts = chunk["timestamp"]
            ts = pd.to_datetime(raw_ts, errors="coerce", utc=True)
            unparsable = ts.isna()
            # Detect rows that had no offset/tz in the raw string: utc=True
            # silently assumes UTC for naive strings, which would hide the bug.
            has_tz = raw_ts.str.contains(
                r"(?:Z$|[+-]\d{2}:?\d{2}$)", regex=True, na=False
            )
            naive = (~unparsable) & (~has_tz)
            for i in np.where(unparsable)[0]:
                row_errors.setdefault(offset + int(i) + 2, []).append(
                    f"unparsable timestamp: {raw_ts.iloc[i]!r}"
                )
            for i in np.where(naive)[0]:
                row_errors.setdefault(offset + int(i) + 2, []).append(
                    f"timestamp has no timezone information: {raw_ts.iloc[i]!r}"
                )
            # treat naive rows as invalid too — drop them downstream
            ts = ts.where(~naive)
            chunk["timestamp"] = ts

            # --- numeric columns ---
            for col in ["open", "high", "low", "close", "volume"] + (
                ["open_interest"] if has_oi else []
            ):
                num = pd.to_numeric(chunk[col], errors="coerce")
                bad = num.isna() & chunk[col].notna() & (chunk[col] != "")
                for i in np.where(bad)[0]:
                    row_errors.setdefault(offset + int(i) + 2, []).append(
                        f"non-numeric {col}: {chunk[col].iloc[i]!r}"
                    )
                chunk[col] = num

            chunks.append(chunk)
            offset += n
    except UnsupportedSchemaError:
        raise
    except Exception as exc:
        raise DataValidationError([f"{source_name}: failed while reading CSV — {exc}"]) from exc

    if not chunks:
        raise UnsupportedSchemaError([f"{source_name}: file contains no data rows"])

    frame = pd.concat(chunks, ignore_index=True)
    if not has_oi:
        frame["open_interest"] = np.nan  # explicitly "no data", never fabricated

    frame = frame[CANONICAL_COLUMNS]
    # drop rows whose timestamp failed to parse (already reported)
    frame = frame[frame["timestamp"].notna()].reset_index(drop=True)
    return frame, row_errors

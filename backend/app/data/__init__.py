"""Data layer: CSV ingestion, validation, repositories."""

from app.data.errors import DataValidationError, UnsupportedSchemaError
from app.data.loader import parse_csv
from app.data.repository import InMemoryDataStore, store
from app.data.schemas import CANONICAL_COLUMNS, DataSetMeta, ParsedDataSet
from app.data.store_factory import build_store
from app.data.validator import validate_frame

__all__ = [
    "CANONICAL_COLUMNS",
    "DataSetMeta",
    "DataValidationError",
    "InMemoryDataStore",
    "ParsedDataSet",
    "UnsupportedSchemaError",
    "build_store",
    "parse_csv",
    "store",
    "validate_frame",
]

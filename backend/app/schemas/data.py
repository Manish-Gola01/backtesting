"""Request/response schemas for the data API."""
from typing import Optional

from pydantic import BaseModel, Field


class UploadResponse(BaseModel):
    status: str = "stored"
    symbol: str
    exchange: str
    timeframe: str
    has_oi: bool
    candles: int
    start: str
    end: str
    warnings: list[str] = Field(default_factory=list)


class InstrumentCoverage(BaseModel):
    symbol: str
    exchange: str
    timeframe: str
    has_oi: bool
    candles: int
    start: str
    end: str


class InstrumentListResponse(BaseModel):
    instruments: list[InstrumentCoverage]


class ValidationErrorDetail(BaseModel):
    detail: str
    code: str = "DATA_VALIDATION_FAILED"
    issues: list[str] = Field(default_factory=list)
    row_errors: dict[int, list[str]] = Field(default_factory=dict)


class UploadQuery(BaseModel):
    symbol: str = Field(min_length=1, max_length=32)
    exchange: str = Field(min_length=1, max_length=32)
    timeframe: str = Field(min_length=2, max_length=8)
    require_oi: bool = False
    require_contiguous: bool = False
    overwrite: bool = False
    description: Optional[str] = None

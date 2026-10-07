"""CSV upload + instrument coverage endpoints (Phase 2).

Upload is validated end-to-end before anything is stored: size cap,
extension allow-list, schema, per-row rules. Failures return 422 with every
issue found; nothing invalid is ever persisted.
"""
import logging

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile

from app.core.config import Settings, get_settings
from app.data import DataValidationError, UnsupportedSchemaError, parse_csv, store, validate_frame
from app.schemas.data import (
    InstrumentCoverage,
    InstrumentListResponse,
    UploadResponse,
    ValidationErrorDetail,
)

router = APIRouter(tags=["data"])
logger = logging.getLogger(__name__)

_ALLOWED_EXTENSIONS = {".csv"}


def _check_file(file: UploadFile, settings: Settings, body: bytes) -> None:
    name = file.filename or ""
    if not name.lower().endswith(tuple(_ALLOWED_EXTENSIONS)):
        raise HTTPException(
            status_code=400,
            detail=f"unsupported file type {name!r}; only .csv uploads are accepted",
        )
    limit = settings.MAX_UPLOAD_MB * 1024 * 1024
    if len(body) > limit:
        raise HTTPException(
            status_code=413,
            detail=f"file too large: {len(body) / 1e6:.1f} MB > {settings.MAX_UPLOAD_MB} MB limit",
        )


@router.post(
    "/data/upload",
    response_model=UploadResponse,
    responses={422: {"model": ValidationErrorDetail}},
    status_code=201,
)
async def upload_csv(
    file: UploadFile = File(...),
    symbol: str = Query(min_length=1, max_length=32),
    exchange: str = Query(min_length=1, max_length=32),
    timeframe: str = Query(min_length=2, max_length=8),
    require_oi: bool = Query(False),
    require_contiguous: bool = Query(False),
    overwrite: bool = Query(False),
    settings: Settings = Depends(get_settings),
) -> UploadResponse:
    body = await file.read()
    _check_file(file, settings, body)

    source = file.filename or "upload"
    logger.info("upload received: %s (%d bytes) %s/%s %s", source, len(body), symbol, exchange, timeframe)

    import io

    try:
        frame, row_errors = parse_csv(io.BytesIO(body), source_name=source)
        ds = validate_frame(
            frame,
            symbol=symbol,
            exchange=exchange,
            timeframe=timeframe,
            require_oi=require_oi,
            require_contiguous=require_contiguous,
            preexisting_row_errors=row_errors,
        )
        store.save(ds, overwrite=overwrite)
    except UnsupportedSchemaError as exc:
        logger.info("upload rejected (schema): %s", exc.issues[:2])
        raise HTTPException(
            status_code=422,
            detail={
                "detail": "; ".join(exc.issues),
                "code": "DATA_SCHEMA_INVALID",
                "issues": exc.issues,
                "row_errors": exc.row_errors,
            },
        ) from exc
    except DataValidationError as exc:
        logger.info("upload rejected (%d issues, %d bad rows)", len(exc.issues), len(exc.row_errors))
        raise HTTPException(
            status_code=422,
            detail={
                "detail": "; ".join(exc.issues) or "row-level validation failed",
                "code": "DATA_VALIDATION_FAILED",
                "issues": exc.issues,
                "row_errors": exc.row_errors,
            },
        ) from exc

    warnings = list(getattr(ds, "warnings", []))
    logger.info(
        "upload stored: %s/%s %s — %d candles, oi=%s, %d warning(s)",
        ds.meta.symbol, ds.meta.exchange, ds.meta.timeframe, ds.candles, ds.meta.has_oi, len(warnings),
    )
    return UploadResponse(**ds.summary(), warnings=warnings)


@router.get("/instruments", response_model=InstrumentListResponse)
def list_instruments() -> InstrumentListResponse:
    """Coverage of every uploaded dataset (Phase 2: in-memory)."""
    return InstrumentListResponse(
        instruments=[InstrumentCoverage(**row) for row in store.coverage()]
    )

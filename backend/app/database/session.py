"""Database engine/session factory — engine-agnostic.

The URL comes from Settings.DATABASE_URL:
- PostgreSQL (production):  postgresql+psycopg://user:pass@host:5432/db
- SQLite (local verification):  sqlite:///path/to.db

`check_same_thread` is only relevant for SQLite and is applied conditionally.
"""
from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


def make_engine(url: str) -> Engine:
    kwargs: dict = {"pool_pre_ping": True, "future": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
        kwargs.pop("pool_pre_ping")  # not supported meaningfully for sqlite
    return create_engine(url, **kwargs)


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, class_=Session, autoflush=False, expire_on_commit=False)


# Convenience accessors used by FastAPI dependencies / services (Phase 7).
_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def init_engine(url: str) -> Engine:
    global _engine, _SessionLocal
    _engine = make_engine(url)
    _SessionLocal = make_session_factory(_engine)
    return _engine


def get_engine() -> Engine:
    if _engine is None:
        from app.core.config import get_settings

        init_engine(get_settings().DATABASE_URL)
    assert _engine is not None
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    if _SessionLocal is None:
        get_engine()
    assert _SessionLocal is not None
    return _SessionLocal

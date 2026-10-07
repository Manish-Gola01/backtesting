"""Chooses the active data store based on configuration.

- `DATA_BACKEND=memory` (default for tests)  -> InMemoryDataStore
- `DATA_BACKEND=db`                          -> SqlAlchemyDataStore on DATABASE_URL

This indirection means the API layer never changes when we move engines.
"""
from __future__ import annotations

import os

from app.data.db_repository import SqlAlchemyDataStore
from app.data.repository import InMemoryDataStore


def build_store():
    backend = os.environ.get("DATA_BACKEND", "memory").lower()
    if backend == "db":
        from app.core.config import get_settings
        from app.database.session import get_session_factory

        return SqlAlchemyDataStore(get_session_factory())
    return InMemoryDataStore()

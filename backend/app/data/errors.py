"""Structured errors raised by the data layer. Mapped to HTTP in the API layer."""
from __future__ import annotations

from typing import Optional


class DataValidationError(Exception):
    """Raised when an uploaded dataset fails validation.

    `issues` is a flat, human-readable list of every problem found (never
    just the first), `row_errors` maps a CSV/data row number to its messages
    so the UI can point at exact lines.
    """

    def __init__(
        self,
        issues: list[str],
        row_errors: Optional[dict[int, list[str]]] = None,
    ) -> None:
        self.issues = issues
        self.row_errors = row_errors or {}
        super().__init__("; ".join(issues[:5]) + (" …" if len(issues) > 5 else ""))


class UnsupportedSchemaError(DataValidationError):
    """Missing required columns or wrong file structure."""

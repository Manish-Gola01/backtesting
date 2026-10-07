"""Background job infrastructure — JobRunner protocol + in-process runner.

Design (docs/ARCHITECTURE.md §7): a backtest is a job with a status machine
QUEUED -> RUNNING -> COMPLETED|FAILED. The runner is swappable: Phase 7 uses
FastAPI BackgroundTasks; Celery/RQ + Redis later without changing the API.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import Lock
from typing import Callable, Optional

logger = logging.getLogger(__name__)


@dataclass
class Job:
    id: str
    kind: str
    status: str = "QUEUED"           # QUEUED|RUNNING|COMPLETED|FAILED
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    error: Optional[str] = None
    result: object = None            # opaque payload (BacktestResult / id)


class JobStore:
    """Thread-safe in-memory job registry (Phase 7). Phase 7.5 may mirror to DB."""
    def __init__(self) -> None:
        self._lock = Lock()
        self._jobs: dict[str, Job] = {}

    def create(self, kind: str) -> Job:
        job = Job(id=str(uuid.uuid4()), kind=kind)
        with self._lock:
            self._jobs[job.id] = job
        return job

    def get(self, job_id: str) -> Optional[Job]:
        return self._jobs.get(job_id)

    def set(self, job_id: str, **fields) -> None:
        with self._lock:
            j = self._jobs.get(job_id)
            if j:
                for k, v in fields.items():
                    setattr(j, k, v)

    def clear(self) -> None:
        with self._lock:
            self._jobs.clear()


job_store = JobStore()


class BackgroundTasksRunner:
    """Runs a callable via FastAPI BackgroundTasks (in-process).

    `submit` returns the job immediately (QUEUED); the wrapped callable
    transitions status and stores the result or the exception.
    """
    def __init__(self, store: JobStore = job_store) -> None:
        self.store = store

    def submit(self, background_tasks, kind: str, fn: Callable[[], object]) -> Job:
        job = self.store.create(kind)

        def _run() -> None:
            self.store.set(job.id, status="RUNNING", started_at=datetime.now(timezone.utc))
            logger.info("job %s (%s) started", job.id, kind)
            try:
                result = fn()
            except Exception as exc:  # noqa: BLE001 - record and surface
                logger.exception("job %s failed", job.id)
                self.store.set(job.id, status="FAILED", error=str(exc),
                               finished_at=datetime.now(timezone.utc))
                return
            self.store.set(job.id, status="COMPLETED", result=result,
                           finished_at=datetime.now(timezone.utc))
            logger.info("job %s completed", job.id)

        background_tasks.add_task(_run)
        return job

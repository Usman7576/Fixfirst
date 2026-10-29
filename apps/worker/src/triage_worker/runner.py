"""Claims one job at a time, keeps its lease alive while the handler runs, and reaps
jobs abandoned by crashed workers."""

import asyncio
import contextlib
import time
from datetime import timedelta

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from triage_core.settings import Settings
from triage_db import jobs
from triage_db.models import Job
from triage_worker.handlers import HANDLERS, ON_FINAL_FAILURE, Handler, PermanentJobError

REAP_INTERVAL_S = 30.0

log = structlog.get_logger()


class JobRunner:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        settings: Settings,
        worker_id: str,
        handlers: dict[str, Handler] | None = None,
    ) -> None:
        self._sessions = sessions
        self._worker_id = worker_id
        self._lease = timedelta(seconds=settings.job_lease_s)
        self._handlers = handlers if handlers is not None else HANDLERS
        self._last_reap = float("-inf")

    async def run_once(self) -> bool:
        """Processes at most one job. Returns True if it did any work."""
        await self._maybe_reap()
        async with self._sessions() as session:
            job = await jobs.claim(session, self._worker_id, self._lease)
        if job is None:
            return False
        await self._run(job)
        return True

    async def _run(self, job: Job) -> None:
        bound = structlog.contextvars.bound_contextvars(
            job_id=str(job.id), job_kind=job.kind, attempt=job.attempts
        )
        with bound:
            handler = self._handlers.get(job.kind)
            heartbeat = asyncio.create_task(self._heartbeat(job))
            try:
                if handler is None:
                    raise PermanentJobError(f"no handler for job kind {job.kind!r}")
                log.info("job.started")
                await handler(self._sessions, job.payload)
            except Exception as exc:
                await self._handle_failure(job, exc)
            else:
                async with self._sessions() as session:
                    await jobs.complete(session, job.id, self._worker_id)
                log.info("job.completed")
            finally:
                heartbeat.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await heartbeat

    async def _handle_failure(self, job: Job, exc: Exception) -> None:
        error = f"{type(exc).__name__}: {exc}"
        if isinstance(exc, PermanentJobError):
            job.attempts = job.max_attempts  # don't retry
        async with self._sessions() as session:
            will_retry = await jobs.fail(session, job, self._worker_id, error)
        if will_retry:
            log.warning("job.failed_will_retry", error=error)
            return
        log.error("job.failed_permanently", error=error, exc_info=exc)
        await self._final_failure(job, error)

    async def _final_failure(self, job: Job, error: str) -> None:
        on_failure = ON_FINAL_FAILURE.get(job.kind)
        if on_failure is not None:
            await on_failure(self._sessions, job.payload, error)

    async def _heartbeat(self, job: Job) -> None:
        interval = self._lease.total_seconds() / 3
        while True:
            await asyncio.sleep(interval)
            async with self._sessions() as session:
                if not await jobs.heartbeat(session, job.id, self._worker_id, self._lease):
                    log.error("job.lease_lost")
                    return

    async def _maybe_reap(self) -> None:
        if time.monotonic() - self._last_reap < REAP_INTERVAL_S:
            return
        self._last_reap = time.monotonic()
        async with self._sessions() as session:
            requeued, failed = await jobs.reap_expired(session)
        for job in requeued:
            log.warning("job.reaped_requeued", job_id=str(job.id))
        for job in failed:
            log.error("job.reaped_failed", job_id=str(job.id))
            await self._final_failure(job, job.last_error or "lease expired")

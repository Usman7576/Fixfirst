"""Postgres job queue (ADR 0001): SKIP LOCKED claims, leases kept alive by heartbeats,
a reaper for expired leases, and exponential-backoff retries."""

import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from triage_core.domain import JobStatus
from triage_db.models import Job

RETRY_DELAYS = (timedelta(seconds=30), timedelta(minutes=2), timedelta(minutes=10))


def enqueue(
    session: AsyncSession,
    kind: str,
    payload: dict[str, Any],
    *,
    max_attempts: int = 3,
    priority: int = 0,
) -> Job:
    """Adds the job to the caller's transaction so it commits atomically with related rows."""
    job = Job(kind=kind, payload=payload, max_attempts=max_attempts, priority=priority)
    session.add(job)
    return job


async def claim(session: AsyncSession, worker_id: str, lease: timedelta) -> Job | None:
    ready = (
        select(Job.id)
        .where(Job.status == JobStatus.QUEUED, Job.run_after <= func.now())
        .order_by(Job.priority.desc(), Job.run_after, Job.created_at)
        .limit(1)
        .with_for_update(skip_locked=True)
        .scalar_subquery()
    )
    job = await session.scalar(
        update(Job)
        .where(Job.id == ready)
        .values(
            status=JobStatus.RUNNING,
            attempts=Job.attempts + 1,
            lease_until=func.now() + lease,
            locked_by=worker_id,
        )
        .returning(Job)
    )
    await session.commit()
    return job


async def heartbeat(
    session: AsyncSession, job_id: uuid.UUID, worker_id: str, lease: timedelta
) -> bool:
    """Extends the lease. False means the job was reaped and another worker may own it."""
    result = await session.execute(
        update(Job)
        .where(Job.id == job_id, Job.locked_by == worker_id, Job.status == JobStatus.RUNNING)
        .values(lease_until=func.now() + lease)
        .returning(Job.id)
    )
    await session.commit()
    return result.scalar() is not None


async def complete(session: AsyncSession, job_id: uuid.UUID, worker_id: str) -> None:
    await session.execute(
        update(Job)
        .where(Job.id == job_id, Job.locked_by == worker_id)
        .values(status=JobStatus.DONE, lease_until=None)
    )
    await session.commit()


async def fail(session: AsyncSession, job: Job, worker_id: str, error: str) -> bool:
    """Schedules a retry with backoff, or marks the job failed. Returns True if it will retry."""
    retry = job.attempts < job.max_attempts
    values: dict[str, Any] = {"last_error": error[:2000], "lease_until": None, "locked_by": None}
    if retry:
        delay = RETRY_DELAYS[min(job.attempts - 1, len(RETRY_DELAYS) - 1)]
        values |= {"status": JobStatus.QUEUED, "run_after": func.now() + delay}
    else:
        values["status"] = JobStatus.FAILED
    await session.execute(
        update(Job).where(Job.id == job.id, Job.locked_by == worker_id).values(**values)
    )
    await session.commit()
    return retry


async def reap_expired(session: AsyncSession) -> tuple[list[Job], list[Job]]:
    """Re-queues jobs whose worker vanished; fails those out of attempts.

    Returns (requeued, failed) so the caller can update domain rows for failures.
    """
    expired = (Job.status == JobStatus.RUNNING) & (Job.lease_until < func.now())
    requeued = (
        await session.scalars(
            update(Job)
            .where(expired, Job.attempts < Job.max_attempts)
            .values(status=JobStatus.QUEUED, lease_until=None, locked_by=None, run_after=func.now())
            .returning(Job)
        )
    ).all()
    failed = (
        await session.scalars(
            update(Job)
            .where(expired, Job.attempts >= Job.max_attempts)
            .values(
                status=JobStatus.FAILED,
                lease_until=None,
                locked_by=None,
                last_error="lease expired: worker stopped responding",
            )
            .returning(Job)
        )
    ).all()
    await session.commit()
    return list(requeued), list(failed)

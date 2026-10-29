"""Job queue behaviour against real Postgres: claims, leases, retries, reaping."""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from triage_core.domain import JobKind, JobStatus, ScanStatus
from triage_core.settings import Settings
from triage_db import jobs
from triage_db.models import Job, Repository, Scan, Team
from triage_worker.handlers import run_scan
from triage_worker.runner import JobRunner

pytestmark = pytest.mark.integration

Sessions = async_sessionmaker[AsyncSession]
LEASE = timedelta(seconds=60)


async def _scan_job(sessions: Sessions, *, max_attempts: int = 3) -> tuple[uuid.UUID, uuid.UUID]:
    async with sessions() as session:
        team = Team(name="t")
        session.add(team)
        await session.flush()
        repo = Repository(
            team_id=team.id,
            github_repo_id=int(uuid.uuid4().int % 10**9),
            github_full_name="acme/app",
            default_branch="main",
            is_private=False,
        )
        session.add(repo)
        await session.flush()
        scan = Scan(repo_id=repo.id)
        session.add(scan)
        await session.flush()
        job = jobs.enqueue(
            session, JobKind.SCAN, {"scan_id": str(scan.id)}, max_attempts=max_attempts
        )
        await session.commit()
        return job.id, scan.id


async def _get(sessions: Sessions, model: Any, key: uuid.UUID) -> Any:
    async with sessions() as session:
        return await session.get(model, key)


async def test_runner_completes_a_scan_job(sessions: Sessions, settings: Settings) -> None:
    job_id, scan_id = await _scan_job(sessions)

    did_work = await JobRunner(sessions, settings, "w1").run_once()

    assert did_work
    job, scan = await _get(sessions, Job, job_id), await _get(sessions, Scan, scan_id)
    assert job.status is JobStatus.DONE
    assert job.attempts == 1
    assert scan.status is ScanStatus.DONE
    assert scan.started_at is not None
    assert scan.finished_at is not None


async def test_idle_runner_reports_no_work(sessions: Sessions, settings: Settings) -> None:
    assert await JobRunner(sessions, settings, "w1").run_once() is False


async def test_concurrent_claims_never_return_the_same_job(sessions: Sessions) -> None:
    for _ in range(3):
        await _scan_job(sessions)

    async def claim(worker: str) -> uuid.UUID | None:
        async with sessions() as session:
            job = await jobs.claim(session, worker, LEASE)
            return job.id if job else None

    claimed = await asyncio.gather(*(claim(f"w{i}") for i in range(5)))

    ids = [c for c in claimed if c is not None]
    assert len(ids) == 3
    assert len(set(ids)) == 3


async def test_failed_job_is_retried_later_with_backoff(
    sessions: Sessions, settings: Settings
) -> None:
    job_id, _ = await _scan_job(sessions)

    async def boom(_: Sessions, __: dict[str, Any]) -> None:
        raise RuntimeError("clone timed out")

    await JobRunner(sessions, settings, "w1", handlers={JobKind.SCAN: boom}).run_once()

    job = await _get(sessions, Job, job_id)
    assert job.status is JobStatus.QUEUED
    assert job.run_after > datetime.now(UTC) + timedelta(seconds=20)
    assert "clone timed out" in job.last_error
    # Not runnable yet, so an immediate poll finds nothing.
    assert await JobRunner(sessions, settings, "w2").run_once() is False


async def test_job_out_of_attempts_fails_and_marks_the_scan_failed(
    sessions: Sessions, settings: Settings
) -> None:
    job_id, scan_id = await _scan_job(sessions, max_attempts=1)

    async def boom(_: Sessions, __: dict[str, Any]) -> None:
        raise RuntimeError("semgrep crashed")

    await JobRunner(sessions, settings, "w1", handlers={JobKind.SCAN: boom}).run_once()

    job, scan = await _get(sessions, Job, job_id), await _get(sessions, Scan, scan_id)
    assert job.status is JobStatus.FAILED
    assert scan.status is ScanStatus.FAILED
    assert "semgrep crashed" in scan.failure_reason


async def test_unknown_job_kind_fails_without_retrying(
    sessions: Sessions, settings: Settings
) -> None:
    job_id, _ = await _scan_job(sessions)

    await JobRunner(sessions, settings, "w1", handlers={}).run_once()

    assert (await _get(sessions, Job, job_id)).status is JobStatus.FAILED


async def _expire_lease(sessions: Sessions, job_id: uuid.UUID, attempts: int) -> None:
    async with sessions() as session:
        await session.execute(
            update(Job)
            .where(Job.id == job_id)
            .values(
                status=JobStatus.RUNNING,
                locked_by="dead-worker",
                attempts=attempts,
                lease_until=datetime.now(UTC) - timedelta(minutes=1),
            )
        )
        await session.commit()


async def test_reaper_requeues_jobs_from_dead_workers(
    sessions: Sessions, settings: Settings
) -> None:
    job_id, _ = await _scan_job(sessions)
    await _expire_lease(sessions, job_id, attempts=1)

    # The reap runs first in run_once, then the same runner picks the job back up.
    await JobRunner(sessions, settings, "w2").run_once()

    job = await _get(sessions, Job, job_id)
    assert job.status is JobStatus.DONE
    assert job.attempts == 2
    assert job.locked_by == "w2"


async def test_reaper_fails_jobs_out_of_attempts(sessions: Sessions, settings: Settings) -> None:
    job_id, scan_id = await _scan_job(sessions, max_attempts=2)
    await _expire_lease(sessions, job_id, attempts=2)

    await JobRunner(sessions, settings, "w2").run_once()

    assert (await _get(sessions, Job, job_id)).status is JobStatus.FAILED
    scan = await _get(sessions, Scan, scan_id)
    assert scan.status is ScanStatus.FAILED
    assert "lease expired" in scan.failure_reason


async def test_heartbeat_fails_once_another_worker_owns_the_job(sessions: Sessions) -> None:
    job_id, _ = await _scan_job(sessions)
    async with sessions() as session:
        await jobs.claim(session, "w1", LEASE)
    await _expire_lease(sessions, job_id, attempts=1)
    async with sessions() as session:
        await jobs.reap_expired(session)
        await jobs.claim(session, "w2", LEASE)

    async with sessions() as session:
        assert await jobs.heartbeat(session, job_id, "w1", LEASE) is False
        assert await jobs.heartbeat(session, job_id, "w2", LEASE) is True


async def test_scan_handler_is_idempotent(sessions: Sessions) -> None:
    _, scan_id = await _scan_job(sessions)

    await run_scan(sessions, {"scan_id": str(scan_id)})
    first = await _get(sessions, Scan, scan_id)
    await run_scan(sessions, {"scan_id": str(scan_id)})
    second = await _get(sessions, Scan, scan_id)

    assert second.status is ScanStatus.DONE
    assert second.started_at == first.started_at


async def test_cancelled_scan_is_skipped(sessions: Sessions) -> None:
    _, scan_id = await _scan_job(sessions)
    async with sessions() as session:
        await session.execute(
            update(Scan).where(Scan.id == scan_id).values(status=ScanStatus.CANCELLED)
        )
        await session.commit()

    await run_scan(sessions, {"scan_id": str(scan_id)})

    async with sessions() as session:
        status = await session.scalar(select(Scan.status).where(Scan.id == scan_id))
    assert status is ScanStatus.CANCELLED

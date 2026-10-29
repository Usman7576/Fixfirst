"""Job handlers by kind. Each must be idempotent: a job can run again after a crash."""

import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from triage_core.domain import JobKind, ScanStatus
from triage_db.models import Repository, Scan

log = structlog.get_logger()

Handler = Callable[[async_sessionmaker[AsyncSession], dict[str, Any]], Awaitable[None]]


class PermanentJobError(Exception):
    """Retrying won't help (e.g. the scan row is gone); fail the job immediately."""


async def run_scan(sessions: async_sessionmaker[AsyncSession], payload: dict[str, Any]) -> None:
    scan_id = uuid.UUID(payload["scan_id"])
    structlog.contextvars.bind_contextvars(scan_id=str(scan_id))
    async with sessions() as session:
        scan = await session.get(Scan, scan_id)
        if scan is None:
            raise PermanentJobError(f"scan {scan_id} not found")
        if scan.status is ScanStatus.CANCELLED:
            log.info("scan.skipped_cancelled")
            return
        scan.status = ScanStatus.RUNNING
        scan.started_at = scan.started_at or datetime.now(UTC)
        scan.stage = "starting"
        await session.commit()

        # Week 3 adds the real stages here: clone → scan → normalise → dedupe → reconcile.
        log.warning("scan.pipeline_not_implemented")

        now = datetime.now(UTC)
        scan.status = ScanStatus.DONE
        scan.stage = "done"
        scan.finished_at = now
        await session.execute(
            update(Repository).where(Repository.id == scan.repo_id).values(last_scanned_at=now)
        )
        await session.commit()
    log.info("scan.completed")


async def mark_scan_failed(
    sessions: async_sessionmaker[AsyncSession], payload: dict[str, Any], reason: str
) -> None:
    """Called once a scan job has used up its retries, so the UI shows why it stopped."""
    try:
        scan_id = uuid.UUID(payload["scan_id"])
    except (KeyError, ValueError):
        return
    async with sessions() as session:
        await session.execute(
            update(Scan)
            .where(Scan.id == scan_id)
            .values(
                status=ScanStatus.FAILED,
                finished_at=datetime.now(UTC),
                failure_reason=reason[:1000],
            )
        )
        await session.commit()


HANDLERS: dict[str, Handler] = {JobKind.SCAN: run_scan}

# What to do to domain rows when a job of this kind gives up for good.
ON_FINAL_FAILURE: dict[str, Callable[..., Awaitable[None]]] = {JobKind.SCAN: mark_scan_failed}

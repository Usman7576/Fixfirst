"""Job handlers by kind. Each must be idempotent: a job can run again after a crash."""

import asyncio
import shutil
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import structlog
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from triage_core.domain import JobKind, ScanKind, ScanStatus
from triage_core.findings import Finding
from triage_core.fingerprint import assign_fingerprints
from triage_core.settings import Settings
from triage_db.models import Repository, Scan
from triage_db.reconcile import reconcile
from triage_worker import sandbox
from triage_worker.errors import PermanentJobError
from triage_worker.scanners.osv import parse_osv, run_osv
from triage_worker.scanners.semgrep import parse_semgrep, run_semgrep

log = structlog.get_logger()

Sessions = async_sessionmaker[AsyncSession]
Handler = Callable[[Sessions, dict[str, Any]], Awaitable[None]]


async def scan_with_all_tools(src: Path, settings: Settings) -> list[Finding]:
    semgrep, osv = await asyncio.gather(run_semgrep(src, settings), run_osv(src, settings))
    return parse_semgrep(semgrep, src, settings.semgrep_rules_dir) + parse_osv(osv, src)


@dataclass(frozen=True)
class ScanTools:
    """The parts that touch the network and external binaries, swappable in tests."""

    clone: Callable[[str, str, Path, Settings], Awaitable[str]] = sandbox.clone
    scan: Callable[[Path, Settings], Awaitable[list[Finding]]] = scan_with_all_tools


async def run_scan(
    sessions: Sessions, payload: dict[str, Any], settings: Settings, tools: ScanTools
) -> None:
    scan_id = uuid.UUID(payload["scan_id"])
    structlog.contextvars.bind_contextvars(scan_id=str(scan_id))
    workdir = settings.scan_work_dir / str(scan_id)
    async with sessions() as session:
        scan = await session.get(Scan, scan_id)
        if scan is None:
            raise PermanentJobError("Scan no longer exists")
        if scan.status in (ScanStatus.CANCELLED, ScanStatus.DONE):
            log.info("scan.skipped", status=scan.status)
            return
        repo = await session.get(Repository, scan.repo_id)
        if repo is None or repo.deleted_at is not None:
            raise PermanentJobError("Repository was disconnected")

        async def stage(name: str, **progress: Any) -> None:
            scan.stage = name
            scan.progress = {"stage": name, **progress}
            await session.commit()
            log.info("scan.stage", stage=name)

        scan.status = ScanStatus.RUNNING
        scan.started_at = scan.started_at or datetime.now(UTC)
        scan.failure_reason = None
        await stage("cloning")

        shutil.rmtree(workdir, ignore_errors=True)  # leftovers from a crashed attempt
        workdir.mkdir(parents=True)
        try:
            src = workdir / "src"
            scan.commit_sha = await tools.clone(
                repo.github_full_name, repo.default_branch, src, settings
            )
            await stage("scanning", commit_sha=scan.commit_sha)

            findings = assign_fingerprints(await tools.scan(src, settings))
            await stage("reconciling", raw_count=len(findings))

            result = await reconcile(session, scan, findings, full_scan=scan.kind is ScanKind.FULL)
            now = datetime.now(UTC)
            scan.raw_count = result.raw_count
            scan.issue_count = result.issue_count
            scan.status = ScanStatus.DONE
            scan.finished_at = now
            repo.last_scanned_at = now
            await stage(
                "done",
                raw_count=result.raw_count,
                issue_count=result.issue_count,
                new=result.new,
                reopened=result.reopened,
                fixed=result.fixed,
            )
        finally:
            shutil.rmtree(workdir, ignore_errors=True)
    log.info("scan.completed", raw=result.raw_count, issues=result.issue_count, fixed=result.fixed)


async def mark_scan_failed(sessions: Sessions, payload: dict[str, Any], reason: str) -> None:
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


def build_handlers(settings: Settings, tools: ScanTools | None = None) -> dict[str, Handler]:
    scan_tools = tools or ScanTools()

    async def scan(sessions: Sessions, payload: dict[str, Any]) -> None:
        await run_scan(sessions, payload, settings, scan_tools)

    return {JobKind.SCAN: scan}


# What to do to domain rows when a job of this kind gives up for good.
ON_FINAL_FAILURE: dict[str, Callable[[Sessions, dict[str, Any], str], Awaitable[None]]] = {
    JobKind.SCAN: mark_scan_failed
}

"""Starting scans and reading their progress. The work itself happens in the worker."""

import uuid

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from triage_api.authz import ANY_ROLE, WRITERS, get_repo_for, get_scan_for
from triage_api.deps import CurrentUser, SessionDep, SettingsDep, client_ip
from triage_api.schemas import ScanOut, ScanSummary
from triage_core.domain import ACTIVE_SCAN_STATUSES, JobKind, ScanKind
from triage_db import audit, jobs
from triage_db.models import Scan

router = APIRouter(tags=["scans"])


@router.post("/repos/{repo_id}/scans", response_model=ScanOut, status_code=202)
async def start_scan(
    repo_id: uuid.UUID,
    request: Request,
    user: CurrentUser,
    session: SessionDep,
    settings: SettingsDep,
) -> ScanOut:
    repo = await get_repo_for(session, user, repo_id, WRITERS)
    scan = Scan(repo_id=repo.id, kind=ScanKind.FULL, triggered_by=user.id)
    session.add(scan)
    try:
        # The partial unique index allows one active scan per repo; this also absorbs
        # double-clicks without an idempotency key.
        await session.flush()
    except IntegrityError:
        await session.rollback()
        active = await session.scalar(
            select(Scan.id).where(Scan.repo_id == repo_id, Scan.status.in_(ACTIVE_SCAN_STATUSES))
        )
        raise HTTPException(409, f"A scan is already in progress: {active}") from None

    jobs.enqueue(
        session, JobKind.SCAN, {"scan_id": str(scan.id)}, max_attempts=settings.job_max_attempts
    )
    audit.record(
        session,
        action="scan.started",
        entity="scan",
        entity_id=scan.id,
        team_id=repo.team_id,
        user_id=user.id,
        ip=client_ip(request),
    )
    await session.commit()
    await session.refresh(scan)
    return ScanOut.model_validate(scan)


@router.get("/repos/{repo_id}/scans", response_model=list[ScanSummary])
async def scan_history(
    repo_id: uuid.UUID, user: CurrentUser, session: SessionDep, limit: int = 20
) -> list[ScanSummary]:
    await get_repo_for(session, user, repo_id, ANY_ROLE)
    scans = await session.scalars(
        select(Scan)
        .where(Scan.repo_id == repo_id)
        .order_by(Scan.created_at.desc())
        .limit(min(max(limit, 1), 100))
    )
    return [ScanSummary.model_validate(s) for s in scans]


@router.get("/scans/{scan_id}", response_model=ScanOut)
async def get_scan(scan_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> ScanOut:
    scan, _ = await get_scan_for(session, user, scan_id, ANY_ROLE)
    return ScanOut.model_validate(scan)

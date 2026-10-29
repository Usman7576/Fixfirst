"""Team-scoped authorization. Every repository/scan/issue lookup goes through these helpers."""

import uuid

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from triage_core.domain import Role
from triage_db.models import Membership, Repository, Scan, User

ANY_ROLE = frozenset(Role)
WRITERS = frozenset({Role.ADMIN, Role.DEVELOPER})
ADMINS = frozenset({Role.ADMIN})


async def require_role(
    session: AsyncSession, user: User, team_id: uuid.UUID, allowed: frozenset[Role]
) -> Membership:
    """404 for non-members (don't reveal the team exists), 403 for members without the role."""
    membership = await session.get(Membership, (team_id, user.id))
    if membership is None:
        raise HTTPException(404, "Team not found")
    if membership.role not in allowed:
        raise HTTPException(403, f"Requires role: {', '.join(sorted(allowed))}")
    return membership


async def get_repo_for(
    session: AsyncSession, user: User, repo_id: uuid.UUID, allowed: frozenset[Role]
) -> Repository:
    repo = await session.scalar(
        select(Repository).where(Repository.id == repo_id, Repository.deleted_at.is_(None))
    )
    if repo is None:
        raise HTTPException(404, "Repository not found")
    try:
        await require_role(session, user, repo.team_id, allowed)
    except HTTPException as exc:
        if exc.status_code == 404:
            raise HTTPException(404, "Repository not found") from None
        raise
    return repo


async def get_scan_for(
    session: AsyncSession, user: User, scan_id: uuid.UUID, allowed: frozenset[Role]
) -> tuple[Scan, Repository]:
    scan = await session.get(Scan, scan_id)
    if scan is None:
        raise HTTPException(404, "Scan not found")
    try:
        repo = await get_repo_for(session, user, scan.repo_id, allowed)
    except HTTPException as exc:
        if exc.status_code == 404:
            raise HTTPException(404, "Scan not found") from None
        raise
    return scan, repo

"""Append-only audit trail of state-changing actions (plan section 15)."""

import uuid
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from triage_db.models import AuditLog


def record(
    session: AsyncSession,
    *,
    action: str,
    entity: str,
    entity_id: object | None,
    team_id: uuid.UUID | None,
    user_id: uuid.UUID | None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    ip: str | None = None,
) -> None:
    """Adds the entry to the caller's transaction, so it commits or rolls back with the change."""
    session.add(
        AuditLog(
            team_id=team_id,
            user_id=user_id,
            action=action,
            entity=entity,
            entity_id=str(entity_id) if entity_id is not None else None,
            before=before,
            after=after,
            ip=ip,
            request_id=structlog.contextvars.get_contextvars().get("request_id"),
        )
    )

"""Liveness and readiness probes for the hosting platform and uptime checks."""

from typing import Literal

import structlog
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncEngine

from triage_api.errors import problem
from triage_db.engine import migration_state

router = APIRouter(tags=["health"])
log = structlog.get_logger()


class Health(BaseModel):
    status: Literal["ok"] = "ok"


class Readiness(BaseModel):
    status: Literal["ready"] = "ready"
    migration: str | None


@router.get("/health", response_model=Health)
async def health() -> Health:
    """Process is up. Does not touch the database, so a DB outage doesn't restart the API."""
    return Health()


@router.get(
    "/ready",
    response_model=Readiness,
    responses={503: {"description": "Database unreachable or migrations not applied"}},
)
async def ready(request: Request) -> Readiness | JSONResponse:
    """Database reachable and migrated to the latest revision."""
    engine: AsyncEngine = request.app.state.engine
    try:
        state = await migration_state(engine)
    except Exception as exc:  # any driver/network failure means "not ready"
        log.warning("ready.database_unreachable", error=type(exc).__name__)
        return problem(503, "Database unreachable")
    if not state.up_to_date:
        return problem(
            503, "Database migrations are not at head", current=state.current, head=state.head
        )
    return Readiness(migration=state.current)

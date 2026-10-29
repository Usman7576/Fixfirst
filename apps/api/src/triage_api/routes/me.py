"""The signed-in user and their team memberships."""

from fastapi import APIRouter
from sqlalchemy import select

from triage_api.deps import CurrentUser, SessionDep
from triage_api.schemas import Me, TeamMembership
from triage_db.models import Membership, Team

router = APIRouter(tags=["me"])


@router.get("/me", response_model=Me)
async def me(user: CurrentUser, session: SessionDep) -> Me:
    rows = await session.execute(
        select(Membership.team_id, Team.name, Membership.role)
        .join(Team, Team.id == Membership.team_id)
        .where(Membership.user_id == user.id)
        .order_by(Membership.created_at)
    )
    return Me(
        id=user.id,
        login=user.login,
        name=user.name,
        email=user.email,
        avatar_url=user.avatar_url,
        teams=[TeamMembership(team_id=t, team_name=n, role=r) for t, n, r in rows],
    )

"""GitHub OAuth sign-in (state + PKCE), access tokens, and rotating refresh tokens."""

import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

import structlog
from fastapi import APIRouter, Cookie, HTTPException, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from triage_api.deps import CipherDep, GitHubDep, SessionDep, SettingsDep, client_ip
from triage_api.errors import problem
from triage_api.github import GitHubError, GitHubUser
from triage_api.security import (
    InvalidTokenError,
    create_access_token,
    decode_oauth_state,
    encode_oauth_state,
    hash_refresh_token,
    new_oauth_state,
    new_refresh_token,
)
from triage_core.crypto import SecretCipher
from triage_core.domain import Role
from triage_core.settings import Settings
from triage_db import audit
from triage_db.models import Membership, RefreshToken, Team, User

router = APIRouter(prefix="/auth", tags=["auth"])
log = structlog.get_logger()

STATE_COOKIE = "oauth_state"
REFRESH_COOKIE = "refresh_token"
STATE_COOKIE_PATH = "/api/v1/auth/github"
REFRESH_COOKIE_PATH = "/api/v1/auth"
# Two tabs refreshing at once both present the same token; the loser shouldn't trigger
# reuse detection and log the user out everywhere.
CONCURRENT_REFRESH_GRACE = timedelta(seconds=10)


class TokenResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"  # noqa: S105  (OAuth token type, not a secret)
    expires_in: int


@router.get("/github/login", status_code=302, response_class=RedirectResponse)
async def github_login(settings: SettingsDep, github: GitHubDep) -> RedirectResponse:
    if not settings.github_oauth_configured:
        raise HTTPException(503, "GitHub sign-in is not configured on this server")
    oauth = new_oauth_state()
    response = RedirectResponse(github.authorize_url(oauth.state, oauth.code_challenge), 302)
    response.set_cookie(
        STATE_COOKIE,
        encode_oauth_state(settings, oauth),
        max_age=600,
        path=STATE_COOKIE_PATH,
        httponly=True,
        secure=settings.secure_cookies,
        samesite="lax",
    )
    return response


@router.get("/github/callback", status_code=302, response_class=RedirectResponse)
async def github_callback(
    request: Request,
    settings: SettingsDep,
    session: SessionDep,
    github: GitHubDep,
    cipher: CipherDep,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    oauth_state: Annotated[str | None, Cookie()] = None,
) -> RedirectResponse:
    def fail(reason: str) -> RedirectResponse:
        log.info("auth.callback_rejected", reason=reason)
        response = RedirectResponse(f"{settings.web_origin}/login?error={reason}", 302)
        response.delete_cookie(STATE_COOKIE, path=STATE_COOKIE_PATH)
        return response

    if error:
        return fail("access_denied")
    if not code or not state or not oauth_state:
        return fail("invalid_request")
    try:
        expected = decode_oauth_state(settings, oauth_state)
    except InvalidTokenError:
        return fail("invalid_state")
    if not secrets.compare_digest(expected.state, state):
        return fail("invalid_state")

    try:
        gh_token = await github.exchange_code(code, expected.code_verifier)
        gh_user = await github.get_user(gh_token)
    except GitHubError as exc:
        log.warning("auth.github_error", error=str(exc))
        return fail("github_error")

    user = await _upsert_user(session, cipher, gh_user, gh_token, client_ip(request))
    refresh = await _issue_refresh_token(session, settings, user.id, family_id=uuid.uuid4())
    await session.commit()
    log.info("auth.signed_in", user_id=str(user.id))

    response = RedirectResponse(f"{settings.web_origin}/auth/callback", 302)
    response.delete_cookie(STATE_COOKIE, path=STATE_COOKIE_PATH)
    _set_refresh_cookie(response, settings, refresh)
    return response


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    request: Request,
    response: Response,
    settings: SettingsDep,
    session: SessionDep,
    refresh_token: Annotated[str | None, Cookie()] = None,
) -> TokenResponse | JSONResponse:
    _require_web_origin(request, settings)
    if not refresh_token:
        raise HTTPException(401, "No refresh token")

    stored = await session.scalar(
        select(RefreshToken)
        .where(RefreshToken.token_hash == hash_refresh_token(refresh_token))
        .with_for_update()
    )
    now = datetime.now(UTC)
    if stored is None or stored.expires_at <= now:
        return _unauthorized("Refresh token invalid or expired")
    if stored.revoked_at is not None:
        if now - stored.revoked_at <= CONCURRENT_REFRESH_GRACE:
            # Keep the cookie: the winning request already set a fresh one.
            raise HTTPException(401, "Refresh token already used")
        # A rotated-out token came back: assume theft and end every session in the family.
        await _revoke_family(session, stored.family_id, now)
        audit.record(
            session,
            action="auth.refresh_reuse_detected",
            entity="user",
            entity_id=stored.user_id,
            team_id=None,
            user_id=stored.user_id,
            ip=client_ip(request),
        )
        await session.commit()
        log.warning("auth.refresh_reuse_detected", user_id=str(stored.user_id))
        return _unauthorized("Refresh token already used")

    stored.revoked_at = now
    new_token = await _issue_refresh_token(session, settings, stored.user_id, stored.family_id)
    await session.commit()
    _set_refresh_cookie(response, settings, new_token)
    return TokenResponse(
        access_token=create_access_token(settings, stored.user_id),
        expires_in=settings.access_token_ttl_s,
    )


@router.post("/logout", status_code=204)
async def logout(
    request: Request,
    response: Response,
    settings: SettingsDep,
    session: SessionDep,
    refresh_token: Annotated[str | None, Cookie()] = None,
) -> None:
    _require_web_origin(request, settings)
    if refresh_token:
        stored = await session.scalar(
            select(RefreshToken).where(RefreshToken.token_hash == hash_refresh_token(refresh_token))
        )
        if stored is not None:
            await _revoke_family(session, stored.family_id, datetime.now(UTC))
            await session.commit()
    _clear_refresh_cookie(response)


def _require_web_origin(request: Request, settings: Settings) -> None:
    """Cookie-authenticated POSTs: reject other origins (SameSite=Lax is the first line)."""
    origin = request.headers.get("origin")
    if origin is not None and origin != settings.web_origin:
        raise HTTPException(403, "Origin not allowed")


async def _upsert_user(
    session: AsyncSession, cipher: SecretCipher, gh: GitHubUser, gh_token: str, ip: str | None
) -> User:
    user = await session.scalar(select(User).where(User.github_id == gh.id))
    is_new = user is None
    if user is None:
        user = User(github_id=gh.id, login=gh.login)
        session.add(user)
    user.login = gh.login
    user.name = gh.name
    user.email = gh.email
    user.avatar_url = gh.avatar_url
    user.gh_token_enc = cipher.encrypt(gh_token)
    user.last_login_at = datetime.now(UTC)
    await session.flush()

    if is_new:
        team = Team(name=f"{gh.login}'s team")
        session.add(team)
        await session.flush()
        session.add(Membership(team_id=team.id, user_id=user.id, role=Role.ADMIN))
        audit.record(
            session,
            action="user.signed_up",
            entity="user",
            entity_id=user.id,
            team_id=team.id,
            user_id=user.id,
            after={"login": gh.login, "team": team.name},
            ip=ip,
        )
    return user


async def _issue_refresh_token(
    session: AsyncSession, settings: Settings, user_id: uuid.UUID, family_id: uuid.UUID
) -> str:
    token, token_hash = new_refresh_token()
    session.add(
        RefreshToken(
            user_id=user_id,
            token_hash=token_hash,
            family_id=family_id,
            expires_at=datetime.now(UTC) + timedelta(seconds=settings.refresh_token_ttl_s),
        )
    )
    await session.flush()
    return token


async def _revoke_family(session: AsyncSession, family_id: uuid.UUID, now: datetime) -> None:
    await session.execute(
        update(RefreshToken)
        .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=now)
    )


def _set_refresh_cookie(response: Response, settings: Settings, token: str) -> None:
    response.set_cookie(
        REFRESH_COOKIE,
        token,
        max_age=settings.refresh_token_ttl_s,
        path=REFRESH_COOKIE_PATH,
        httponly=True,
        secure=settings.secure_cookies,
        samesite="lax",
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(REFRESH_COOKIE, path=REFRESH_COOKIE_PATH)


def _unauthorized(detail: str) -> JSONResponse:
    """401 that also clears the refresh cookie (headers set on a raised error are lost)."""
    response = problem(401, detail)
    _clear_refresh_cookie(response)
    return response

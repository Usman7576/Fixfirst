"""GitHub OAuth sign-in, refresh-token rotation, reuse detection and logout."""

from collections.abc import Callable
from datetime import timedelta
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from triage_api.routes import auth as auth_routes
from triage_core.domain import Role
from triage_db.models import AuditLog, Membership, RefreshToken, User

pytestmark = pytest.mark.integration

WEB = "http://localhost:5173"


def _sign_in(api: TestClient, code: str = "good-code") -> Any:
    login = api.get("/api/v1/auth/github/login")
    state = parse_qs(urlparse(login.headers["location"]).query)["state"][0]
    return api.get("/api/v1/auth/github/callback", params={"code": code, "state": state})


def _refresh(api: TestClient) -> Any:
    return api.post("/api/v1/auth/refresh", headers={"Origin": WEB})


def _set_refresh_cookie(api: TestClient, value: str) -> None:
    api.cookies.clear()
    api.cookies.set("refresh_token", value, domain="testserver.local", path="/api/v1/auth")


def test_login_redirects_to_github_with_state_and_pkce(api: TestClient) -> None:
    response = api.get("/api/v1/auth/github/login")

    assert response.status_code == 302
    query = parse_qs(urlparse(response.headers["location"]).query)
    assert len(query["state"][0]) >= 32
    assert len(query["code_challenge"][0]) == 43  # base64url SHA-256, no padding
    cookie = response.headers["set-cookie"]
    assert "oauth_state=" in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie


def test_login_is_503_when_github_is_not_configured(settings: Any) -> None:
    from triage_api.main import create_app

    with TestClient(create_app(settings), follow_redirects=False) as client:
        response = client.get("/api/v1/auth/github/login")

    assert response.status_code == 503


def test_first_sign_in_creates_user_team_and_admin_membership(
    api: TestClient, fake_github: Any, run_db: Callable[..., Any]
) -> None:
    response = _sign_in(api)

    assert response.status_code == 302
    assert response.headers["location"] == f"{WEB}/auth/callback"
    assert "refresh_token=" in response.headers["set-cookie"]
    # PKCE: the verifier sent to GitHub matches the challenge we advertised.
    assert len(fake_github.exchanged) == 1

    async def check(session: AsyncSession) -> tuple[User, list[Membership], list[str]]:
        user = await session.scalar(select(User).where(User.github_id == 4242))
        assert user is not None
        memberships = list(await session.scalars(select(Membership)))
        actions = list(await session.scalars(select(AuditLog.action)))
        return user, memberships, actions

    user, memberships, actions = run_db(check)
    assert user.login == "octo"
    assert user.gh_token_enc is not None
    assert b"gho_fake" not in user.gh_token_enc  # stored encrypted
    assert [m.role for m in memberships] == [Role.ADMIN]
    assert actions == ["user.signed_up"]


def test_second_sign_in_reuses_the_user_and_team(
    api: TestClient, run_db: Callable[..., Any]
) -> None:
    _sign_in(api)
    _sign_in(api)

    async def counts(session: AsyncSession) -> tuple[int, int]:
        users = len(list(await session.scalars(select(User))))
        memberships = len(list(await session.scalars(select(Membership))))
        return users, memberships

    assert run_db(counts) == (1, 1)


@pytest.mark.parametrize(
    ("params", "with_cookie", "error"),
    [
        ({"code": "good-code", "state": "tampered"}, True, "invalid_state"),
        ({"code": "good-code", "state": "whatever"}, False, "invalid_request"),
        ({"error": "access_denied"}, True, "access_denied"),
        ({"code": "bad-code", "state": None}, True, "github_error"),
    ],
)
def test_callback_rejections_redirect_to_login_with_reason(
    api: TestClient, params: dict[str, Any], with_cookie: bool, error: str
) -> None:
    login = api.get("/api/v1/auth/github/login")
    if params.get("state", "") is None:
        params["state"] = parse_qs(urlparse(login.headers["location"]).query)["state"][0]
    if not with_cookie:
        api.cookies.clear()

    response = api.get("/api/v1/auth/github/callback", params=params)

    assert response.status_code == 302
    assert response.headers["location"] == f"{WEB}/login?error={error}"
    assert "refresh_token=" not in response.headers.get("set-cookie", "")


def test_refresh_returns_access_token_that_works_for_me(api: TestClient) -> None:
    _sign_in(api)

    token = _refresh(api).json()["access_token"]
    me = api.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})

    assert me.status_code == 200
    assert me.json()["login"] == "octo"
    assert me.json()["teams"][0]["role"] == "admin"


def test_refresh_rotates_the_token(api: TestClient) -> None:
    _sign_in(api)
    first = api.cookies.get("refresh_token")

    assert _refresh(api).status_code == 200
    assert api.cookies.get("refresh_token") != first


def test_reused_refresh_token_revokes_the_whole_family(
    api: TestClient, monkeypatch: pytest.MonkeyPatch, run_db: Callable[..., Any]
) -> None:
    monkeypatch.setattr(auth_routes, "CONCURRENT_REFRESH_GRACE", timedelta(0))
    _sign_in(api)
    stolen = api.cookies.get("refresh_token")
    assert _refresh(api).status_code == 200
    current = api.cookies.get("refresh_token")

    _set_refresh_cookie(api, stolen)
    reuse = _refresh(api)
    _set_refresh_cookie(api, current)
    after = _refresh(api)

    assert reuse.status_code == 401
    assert after.status_code == 401, "legitimate session must be revoked too"

    async def active(session: AsyncSession) -> int:
        tokens = await session.scalars(
            select(RefreshToken).where(RefreshToken.revoked_at.is_(None))
        )
        return len(list(tokens))

    assert run_db(active) == 0


def test_concurrent_refresh_within_grace_keeps_the_session(api: TestClient) -> None:
    _sign_in(api)
    original = api.cookies.get("refresh_token")
    assert _refresh(api).status_code == 200
    winner = api.cookies.get("refresh_token")

    _set_refresh_cookie(api, original)
    loser = _refresh(api)
    _set_refresh_cookie(api, winner)

    assert loser.status_code == 401
    assert _refresh(api).status_code == 200


def test_refresh_rejects_other_origins(api: TestClient) -> None:
    _sign_in(api)

    response = api.post("/api/v1/auth/refresh", headers={"Origin": "https://evil.example"})

    assert response.status_code == 403


def test_refresh_without_cookie_is_401(api: TestClient) -> None:
    assert _refresh(api).status_code == 401


def test_logout_revokes_the_session(api: TestClient) -> None:
    _sign_in(api)
    token = api.cookies.get("refresh_token")

    assert api.post("/api/v1/auth/logout", headers={"Origin": WEB}).status_code == 204
    _set_refresh_cookie(api, token)

    assert _refresh(api).status_code == 401

"""Every endpoint x every role x cross-team access (plan section 18, "AuthZ suite")."""

from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.integration

ROLES = ("admin", "developer", "viewer", "outsider")

# (method, path template, json body template, expected status per role in ROLES order)
CASES: list[tuple[str, str, dict[str, Any] | None, tuple[int, int, int, int]]] = [
    ("GET", "/api/v1/repos?team_id={team_a}", None, (200, 200, 200, 404)),
    (
        "POST",
        "/api/v1/repos",
        {"team_id": "{team_a}", "github_full_name": "acme/new-repo"},
        (201, 403, 403, 404),
    ),
    ("DELETE", "/api/v1/repos/{repo_a}", None, (204, 403, 403, 404)),
    ("POST", "/api/v1/repos/{repo_a}/scans", None, (202, 202, 403, 404)),
    ("GET", "/api/v1/repos/{repo_a}/scans", None, (200, 200, 200, 404)),
    ("GET", "/api/v1/scans/{scan_a}", None, (200, 200, 200, 404)),
]


def _fill(template: Any, world: Any) -> Any:
    values = {
        "team_a": world.team_a,
        "repo_a": world.repo_a,
        "scan_a": world.scan_a,
    }
    if isinstance(template, str):
        return template.format(**values)
    if isinstance(template, dict):
        return {k: _fill(v, world) for k, v in template.items()}
    return template


@pytest.mark.parametrize(("method", "path", "body", "expected"), CASES)
@pytest.mark.parametrize("role", ROLES)
def test_role_matrix(
    api: TestClient,
    world: Any,
    auth: Callable[..., dict[str, str]],
    run_db: Any,
    method: str,
    path: str,
    body: dict[str, Any] | None,
    expected: tuple[int, int, int, int],
    role: str,
) -> None:
    response = api.request(
        method, _fill(path, world), json=_fill(body, world), headers=auth(world.users[role])
    )

    assert response.status_code == expected[ROLES.index(role)], response.text


@pytest.mark.parametrize(("method", "path", "body", "_expected"), CASES)
def test_every_endpoint_requires_authentication(
    api: TestClient,
    world: Any,
    method: str,
    path: str,
    body: dict[str, Any] | None,
    _expected: object,
) -> None:
    response = api.request(method, _fill(path, world), json=_fill(body, world))

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"


def test_outsider_cannot_see_other_teams_repos_in_listing(
    api: TestClient, world: Any, auth: Callable[..., dict[str, str]]
) -> None:
    response = api.get(
        f"/api/v1/repos?team_id={world.team_b}", headers=auth(world.users["outsider"])
    )

    assert [r["github_full_name"] for r in response.json()] == ["acme/app-b"]


def test_malformed_and_unsigned_tokens_are_rejected(api: TestClient, world: Any) -> None:
    for token in ("not-a-jwt", "eyJhbGciOiJub25lIn0.eyJzdWIiOiJ4In0."):
        response = api.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 401

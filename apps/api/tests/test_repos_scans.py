"""Repository connection rules and scan enqueueing."""

from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from triage_core.domain import JobStatus
from triage_db.models import AuditLog, Job

pytestmark = pytest.mark.integration


@pytest.fixture
def admin(world: Any, auth: Callable[..., dict[str, str]]) -> dict[str, str]:
    return auth(world.users["admin"])


def _connect(api: TestClient, world: Any, headers: dict[str, str], name: str) -> Any:
    return api.post(
        "/api/v1/repos",
        json={"team_id": str(world.team_a), "github_full_name": name},
        headers=headers,
    )


def test_available_repos_mark_private_ones_unconnectable(
    api: TestClient, admin: dict[str, str]
) -> None:
    repos = {r["full_name"]: r for r in api.get("/api/v1/repos/available", headers=admin).json()}

    assert repos["acme/new-repo"]["connectable"] is True
    assert repos["acme/secret-repo"]["connectable"] is False


def test_connecting_a_private_repo_is_rejected(
    api: TestClient, world: Any, admin: dict[str, str]
) -> None:
    response = _connect(api, world, admin, "acme/secret-repo")

    assert response.status_code == 422
    assert "Private repositories" in response.json()["detail"]


def test_connecting_twice_conflicts(api: TestClient, world: Any, admin: dict[str, str]) -> None:
    assert _connect(api, world, admin, "acme/juice-shop").status_code == 201

    assert _connect(api, world, admin, "acme/juice-shop").status_code == 409


def test_disconnect_then_reconnect_restores_the_repo(
    api: TestClient, world: Any, admin: dict[str, str]
) -> None:
    repo_id = _connect(api, world, admin, "acme/juice-shop").json()["id"]
    assert api.delete(f"/api/v1/repos/{repo_id}", headers=admin).status_code == 204
    listed = api.get(f"/api/v1/repos?team_id={world.team_a}", headers=admin).json()
    assert "acme/juice-shop" not in [r["github_full_name"] for r in listed]

    again = _connect(api, world, admin, "acme/juice-shop")

    assert again.status_code == 201
    assert again.json()["id"] == repo_id


@pytest.mark.parametrize("name", ["../etc/passwd", "no-slash", "a/b/c", "owner/na me"])
def test_connect_rejects_malformed_names(
    api: TestClient, world: Any, admin: dict[str, str], name: str
) -> None:
    assert _connect(api, world, admin, name).status_code == 422


def test_unknown_github_repo_is_404(api: TestClient, world: Any, admin: dict[str, str]) -> None:
    assert _connect(api, world, admin, "acme/does-not-exist").status_code == 404


def test_listing_includes_the_latest_scan(
    api: TestClient, world: Any, admin: dict[str, str]
) -> None:
    listed = api.get(f"/api/v1/repos?team_id={world.team_a}", headers=admin).json()

    assert listed[0]["latest_scan"]["id"] == str(world.scan_a)


def test_starting_a_scan_enqueues_one_job_and_blocks_a_second(
    api: TestClient, world: Any, admin: dict[str, str], run_db: Callable[..., Any]
) -> None:
    first = api.post(f"/api/v1/repos/{world.repo_a}/scans", headers=admin)
    second = api.post(f"/api/v1/repos/{world.repo_a}/scans", headers=admin)

    assert first.status_code == 202
    assert first.json()["status"] == "queued"
    assert second.status_code == 409
    assert first.json()["id"] in second.json()["detail"]

    async def jobs(session: AsyncSession) -> list[Job]:
        return list(await session.scalars(select(Job)))

    queued = run_db(jobs)
    assert len(queued) == 1
    assert queued[0].status is JobStatus.QUEUED
    assert queued[0].payload == {"scan_id": first.json()["id"]}


def test_state_changes_are_audit_logged(
    api: TestClient, world: Any, admin: dict[str, str], run_db: Callable[..., Any]
) -> None:
    repo_id = _connect(api, world, admin, "acme/juice-shop").json()["id"]
    api.post(f"/api/v1/repos/{repo_id}/scans", headers=admin)
    api.delete(f"/api/v1/repos/{repo_id}", headers=admin)

    async def log(session: AsyncSession) -> list[tuple[str, Any]]:
        rows = await session.execute(
            select(AuditLog.action, AuditLog.user_id).order_by(AuditLog.created_at)
        )
        return [tuple(r) for r in rows]

    assert run_db(log) == [
        ("repo.connected", world.users["admin"]),
        ("scan.started", world.users["admin"]),
        ("repo.disconnected", world.users["admin"]),
    ]

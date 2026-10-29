from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from triage_api.main import create_app
from triage_core.settings import Settings

# Nothing listens on port 1, so readiness must report the database as unreachable.
UNREACHABLE_DB = "postgresql+asyncpg://u:p@127.0.0.1:1/none"


def _settings(**overrides: object) -> Settings:
    return Settings(database_url=UNREACHABLE_DB, _env_file=None, **overrides)  # type: ignore[arg-type]


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(create_app(_settings())) as client:
        yield client


def test_health_is_ok_without_a_database(client: TestClient) -> None:
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ready_returns_problem_when_database_is_down(client: TestClient) -> None:
    response = client.get("/api/v1/ready")

    assert response.status_code == 503
    assert response.headers["content-type"] == "application/problem+json"
    body = response.json()
    assert body["detail"] == "Database unreachable"
    assert body["request_id"] == response.headers["X-Request-ID"]


def test_unknown_route_is_problem_json(client: TestClient) -> None:
    response = client.get("/api/v1/nope")

    assert response.status_code == 404
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["title"] == "Not Found"


def test_valid_request_id_is_propagated(client: TestClient) -> None:
    response = client.get("/api/v1/health", headers={"X-Request-ID": "abc-123"})

    assert response.headers["X-Request-ID"] == "abc-123"


@pytest.mark.parametrize("bad_id", ["", "has spaces", "x" * 65, "new\nline"])
def test_unsafe_request_id_is_replaced(client: TestClient, bad_id: str) -> None:
    response = client.get("/api/v1/health", headers={"X-Request-ID": bad_id})

    assert response.headers["X-Request-ID"] != bad_id
    assert len(response.headers["X-Request-ID"]) == 32


def test_security_headers_are_set(client: TestClient) -> None:
    response = client.get("/api/v1/health")

    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"


def test_cors_allows_only_the_web_origin(client: TestClient) -> None:
    preflight = {"Access-Control-Request-Method": "GET"}
    allowed = client.options(
        "/api/v1/health", headers={"Origin": "http://localhost:5173", **preflight}
    )
    denied = client.options(
        "/api/v1/health", headers={"Origin": "https://evil.example", **preflight}
    )

    assert allowed.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert "access-control-allow-origin" not in denied.headers


def test_docs_are_disabled_in_production() -> None:
    secrets = {
        "jwt_signing_key": "x" * 40,
        "token_encryption_key": "A" * 43 + "=",
        "github_client_id": "id",
        "github_client_secret": "secret",
    }
    with TestClient(create_app(_settings(environment="production", **secrets))) as client:
        assert client.get("/api/v1/docs").status_code == 404
        assert client.get("/api/v1/openapi.json").status_code == 404


@pytest.mark.integration
@pytest.mark.usefixtures("migrated_db")
def test_ready_when_database_is_migrated(settings: Settings) -> None:
    with TestClient(create_app(settings)) as client:
        response = client.get("/api/v1/ready")

    assert response.status_code == 200
    assert response.json()["status"] == "ready"

import pytest
from pydantic import ValidationError

from triage_core.settings import Environment, Settings

ASYNC_URL = "postgresql+asyncpg://u:p@localhost:5432/db"
DEPLOYED = {
    "jwt_signing_key": "x" * 40,
    "token_encryption_key": "A" * 43 + "=",
    "github_client_id": "client-id",
    "github_client_secret": "client-secret",
}


@pytest.fixture(autouse=True)
def _isolate_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    # CI and Compose set these; the tests here assert on the built-in defaults.
    for name in Settings.model_fields:
        monkeypatch.delenv(name.upper(), raising=False)


def test_defaults_are_local_and_human_readable_logs() -> None:
    settings = Settings(database_url=ASYNC_URL, _env_file=None)  # type: ignore[call-arg]

    assert settings.environment is Environment.LOCAL
    assert not settings.is_production
    assert not settings.json_logs


def test_non_local_environments_log_json() -> None:
    settings = Settings(database_url=ASYNC_URL, environment="staging", **DEPLOYED, _env_file=None)  # type: ignore[call-arg]

    assert settings.json_logs
    assert settings.secure_cookies


@pytest.mark.parametrize("environment", ["staging", "production"])
def test_deployed_environments_require_real_secrets(environment: str) -> None:
    with pytest.raises(ValidationError, match=r"JWT_SIGNING_KEY.*TOKEN_ENCRYPTION_KEY"):
        Settings(database_url=ASYNC_URL, environment=environment, _env_file=None)  # type: ignore[call-arg]


def test_local_uses_fixed_dev_keys_when_unset() -> None:
    settings = Settings(database_url=ASYNC_URL, _env_file=None)  # type: ignore[call-arg]

    assert len(settings.jwt_key) >= 32
    assert settings.fernet_key
    assert not settings.github_oauth_configured


def test_short_jwt_key_is_rejected() -> None:
    with pytest.raises(ValidationError, match="jwt_signing_key"):
        Settings(database_url=ASYNC_URL, jwt_signing_key="too-short", _env_file=None)  # type: ignore[call-arg]


def test_empty_github_secret_means_oauth_not_configured() -> None:
    settings = Settings(  # type: ignore[call-arg]
        database_url=ASYNC_URL, github_client_id="id", github_client_secret="", _env_file=None
    )

    assert not settings.github_oauth_configured


@pytest.mark.parametrize(
    "url",
    ["postgresql://u:p@localhost/db", "postgresql+psycopg://u:p@localhost/db", "sqlite:///x.db"],
)
def test_rejects_database_urls_without_asyncpg(url: str) -> None:
    with pytest.raises(ValidationError, match="asyncpg"):
        Settings(database_url=url, _env_file=None)  # type: ignore[call-arg]


def test_database_url_is_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(ValidationError, match="database_url"):
        Settings(_env_file=None)  # type: ignore[call-arg]

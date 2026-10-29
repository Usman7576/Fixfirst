import pytest
from pydantic import ValidationError

from triage_core.settings import Environment, Settings

ASYNC_URL = "postgresql+asyncpg://u:p@localhost:5432/db"


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
    settings = Settings(database_url=ASYNC_URL, environment="staging", _env_file=None)  # type: ignore[call-arg]

    assert settings.json_logs


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

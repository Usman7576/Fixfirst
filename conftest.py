"""Shared fixtures. Integration tests run only when TEST_DATABASE_URL points at a disposable DB."""

import os

import pytest
from alembic import command

from triage_core.settings import Settings
from triage_db.engine import alembic_config


@pytest.fixture
def test_database_url() -> str:
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL not set")
    return url


@pytest.fixture
def settings(test_database_url: str) -> Settings:
    return Settings(database_url=test_database_url, environment="ci", _env_file=None)  # type: ignore[call-arg]


@pytest.fixture
def migrated_db(test_database_url: str) -> str:
    command.upgrade(alembic_config(test_database_url), "head")
    return test_database_url

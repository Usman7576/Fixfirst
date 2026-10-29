"""Shared fixtures. Integration tests run only when TEST_DATABASE_URL points at a disposable DB."""

import asyncio
import os
from collections.abc import AsyncIterator

import pytest
from alembic import command
from sqlalchemy import NullPool
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from triage_core.settings import Settings
from triage_db import models  # noqa: F401  (registers every table on Base.metadata)
from triage_db.base import Base
from triage_db.engine import alembic_config, create_engine, create_session_factory


@pytest.fixture(scope="session")
def session_database_url() -> str:
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL not set")
    command.upgrade(alembic_config(url), "head")
    return url


@pytest.fixture
def test_database_url(session_database_url: str) -> str:
    return session_database_url


async def _truncate_all(url: str) -> None:
    engine = create_async_engine(url, poolclass=NullPool)
    # DELETE beats TRUNCATE for a handful of rows: TRUNCATE rewrites files per table, which
    # is slow on Docker Desktop volumes.
    async with engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            await conn.execute(table.delete())
    await engine.dispose()


@pytest.fixture
def clean_db(test_database_url: str) -> str:
    """Migrated to head (once per session) and emptied, so each test starts clean."""
    asyncio.run(_truncate_all(test_database_url))
    return test_database_url


@pytest.fixture
def migrated_db(clean_db: str) -> str:
    return clean_db


@pytest.fixture
def settings(clean_db: str) -> Settings:
    return Settings(database_url=clean_db, environment="ci", _env_file=None)  # type: ignore[call-arg]


@pytest.fixture
async def sessions(settings: Settings) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_engine(settings)
    yield create_session_factory(engine)
    await engine.dispose()

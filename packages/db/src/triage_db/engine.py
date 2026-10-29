"""Async engine and session factory, plus the checks used by readiness probes."""

from dataclasses import dataclass

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Connection, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from triage_core.settings import Settings


def create_engine(settings: Settings) -> AsyncEngine:
    return create_async_engine(
        settings.database_url,
        pool_size=settings.db_pool_size,
        pool_pre_ping=True,
        connect_args={"server_settings": {"application_name": f"triage-{settings.environment}"}},
    )


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


def alembic_config(database_url: str | None = None) -> Config:
    config = Config()
    config.set_main_option("script_location", "triage_db:migrations")
    if database_url:
        config.set_main_option("sqlalchemy.url", database_url)
    return config


@dataclass(frozen=True)
class MigrationState:
    current: str | None
    head: str | None

    @property
    def up_to_date(self) -> bool:
        return self.current == self.head


async def ping(engine: AsyncEngine) -> None:
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))


async def migration_state(engine: AsyncEngine) -> MigrationState:
    def _current(conn: Connection) -> str | None:
        return MigrationContext.configure(conn).get_current_revision()

    async with engine.connect() as conn:
        current = await conn.run_sync(_current)
    head = ScriptDirectory.from_config(alembic_config()).get_current_head()
    return MigrationState(current=current, head=head)

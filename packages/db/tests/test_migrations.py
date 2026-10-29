import pytest
from alembic import command
from alembic.script import ScriptDirectory

from triage_core.settings import Settings
from triage_db.engine import alembic_config, create_engine, migration_state, ping


def test_migration_history_is_linear() -> None:
    script = ScriptDirectory.from_config(alembic_config())

    assert len(script.get_heads()) == 1, "multiple Alembic heads: merge them before shipping"


@pytest.mark.integration
def test_upgrade_downgrade_upgrade_round_trip(test_database_url: str) -> None:
    config = alembic_config(test_database_url)

    command.upgrade(config, "head")
    command.downgrade(config, "base")
    command.upgrade(config, "head")


@pytest.mark.integration
@pytest.mark.usefixtures("migrated_db")
async def test_migration_state_reports_head(settings: Settings) -> None:
    engine = create_engine(settings)
    try:
        await ping(engine)
        state = await migration_state(engine)
    finally:
        await engine.dispose()

    assert state.up_to_date
    assert state.current == state.head

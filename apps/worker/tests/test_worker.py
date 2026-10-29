import asyncio
import time
from pathlib import Path

from triage_core.settings import Settings
from triage_worker.healthcheck import is_healthy
from triage_worker.main import worker_loop


def _settings(heartbeat: Path) -> Settings:
    return Settings(  # type: ignore[call-arg]
        database_url="postgresql+asyncpg://u:p@127.0.0.1:1/none",
        worker_poll_interval_s=0.01,
        worker_heartbeat_file=heartbeat,
        _env_file=None,
    )


async def test_loop_writes_heartbeat_and_stops_on_signal(tmp_path: Path) -> None:
    heartbeat = tmp_path / "beat"
    stop = asyncio.Event()

    task = asyncio.create_task(worker_loop(_settings(heartbeat), stop))
    await asyncio.sleep(0.05)
    stop.set()
    await asyncio.wait_for(task, timeout=1)

    assert heartbeat.exists()


def test_healthcheck_fresh_heartbeat_is_healthy(tmp_path: Path) -> None:
    heartbeat = tmp_path / "beat"
    heartbeat.touch()

    assert is_healthy(heartbeat, poll_interval_s=1.0)


def test_healthcheck_stale_heartbeat_is_unhealthy(tmp_path: Path) -> None:
    heartbeat = tmp_path / "beat"
    heartbeat.touch()

    assert not is_healthy(heartbeat, poll_interval_s=1.0, now=time.time() + 60)


def test_healthcheck_missing_heartbeat_is_unhealthy(tmp_path: Path) -> None:
    assert not is_healthy(tmp_path / "missing", poll_interval_s=1.0)

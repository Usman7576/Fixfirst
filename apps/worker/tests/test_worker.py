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


async def _idle() -> bool:
    return False


async def test_loop_writes_heartbeat_and_stops_on_signal(tmp_path: Path) -> None:
    heartbeat = tmp_path / "beat"
    stop = asyncio.Event()

    task = asyncio.create_task(worker_loop(_settings(heartbeat), stop, _idle))
    await asyncio.sleep(0.05)
    stop.set()
    await asyncio.wait_for(task, timeout=1)

    assert heartbeat.exists()


async def test_heartbeat_stays_fresh_during_a_long_job(tmp_path: Path) -> None:
    heartbeat = tmp_path / "beat"
    stop = asyncio.Event()
    touched_during_job: list[float] = []

    async def long_job() -> bool:
        start = heartbeat.stat().st_mtime if heartbeat.exists() else 0.0
        await asyncio.sleep(0.1)
        touched_during_job.append(heartbeat.stat().st_mtime - start)
        stop.set()
        return True

    await asyncio.wait_for(worker_loop(_settings(heartbeat), stop, long_job), timeout=2)

    assert touched_during_job[0] > 0


async def test_poll_errors_do_not_kill_the_loop(tmp_path: Path) -> None:
    stop = asyncio.Event()
    calls = 0

    async def flaky() -> bool:
        nonlocal calls
        calls += 1
        if calls >= 3:
            stop.set()
        raise ConnectionError("database down")

    await asyncio.wait_for(worker_loop(_settings(tmp_path / "beat"), stop, flaky), timeout=2)

    assert calls >= 3


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

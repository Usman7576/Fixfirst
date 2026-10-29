"""Worker process: waits for the database, then polls for jobs until told to stop."""

import asyncio
import contextlib
import os
import signal
import socket

import structlog
from sqlalchemy.ext.asyncio import AsyncEngine

from triage_core.logging import configure_logging
from triage_core.settings import Settings, get_settings
from triage_db.engine import create_engine, ping

WORKER_ID = f"{socket.gethostname()}-{os.getpid()}"
DB_CONNECT_ATTEMPTS = 10

log = structlog.get_logger()


async def wait_for_database(engine: AsyncEngine, attempts: int = DB_CONNECT_ATTEMPTS) -> None:
    for attempt in range(1, attempts + 1):
        try:
            await ping(engine)
            return
        except Exception as exc:
            if attempt == attempts:
                raise
            delay = min(2**attempt, 30)
            log.warning(
                "worker.database_unavailable",
                attempt=attempt,
                retry_in_s=delay,
                error=type(exc).__name__,
            )
            await asyncio.sleep(delay)


async def worker_loop(settings: Settings, stop: asyncio.Event) -> None:
    log.info("worker.started", worker_id=WORKER_ID)
    while not stop.is_set():
        await asyncio.to_thread(settings.worker_heartbeat_file.touch)
        # Week 2: claim the next job with FOR UPDATE SKIP LOCKED, hold a lease, run it.
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=settings.worker_poll_interval_s)
    log.info("worker.stopped", worker_id=WORKER_ID)


def _install_signal_handlers(stop: asyncio.Event) -> None:
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:  # Windows event loop
            signal.signal(sig, lambda *_: loop.call_soon_threadsafe(stop.set))


async def _main(settings: Settings) -> None:
    stop = asyncio.Event()
    _install_signal_handlers(stop)
    engine = create_engine(settings)
    try:
        await wait_for_database(engine)
        await worker_loop(settings, stop)
    finally:
        await engine.dispose()


def run() -> None:
    settings = get_settings()
    configure_logging(settings.log_level, json=settings.json_logs)
    structlog.contextvars.bind_contextvars(worker_id=WORKER_ID)
    asyncio.run(_main(settings))

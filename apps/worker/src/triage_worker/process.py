"""Runs external tools (git, scanners) with a hard timeout and no shell."""

import asyncio
import os
import signal
import sys
from dataclasses import dataclass
from pathlib import Path


class ProcessTimeoutError(Exception):
    pass


@dataclass(frozen=True)
class Completed:
    returncode: int
    stdout: str
    stderr: str


async def run(
    args: list[str],
    *,
    timeout_s: float,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
) -> Completed:
    """Arguments are passed as a list, never through a shell, so repo-controlled strings
    (paths, branch names) can't inject commands."""
    process = await asyncio.create_subprocess_exec(
        *args,
        cwd=cwd,
        env={**os.environ, **(env or {})},
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        # Own process group, so a timeout also kills children (semgrep spawns workers).
        start_new_session=sys.platform != "win32",
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout_s)
    except TimeoutError:
        _kill(process)
        await process.wait()
        raise ProcessTimeoutError(f"{Path(args[0]).name} exceeded {timeout_s:.0f}s") from None
    except asyncio.CancelledError:
        _kill(process)
        raise
    return Completed(
        returncode=process.returncode if process.returncode is not None else -1,
        stdout=stdout.decode(errors="replace"),
        stderr=stderr.decode(errors="replace"),
    )


def _kill(process: asyncio.subprocess.Process) -> None:
    if process.returncode is not None:
        return
    if sys.platform != "win32":
        try:
            os.killpg(process.pid, signal.SIGKILL)
            return
        except ProcessLookupError:
            return
    process.kill()

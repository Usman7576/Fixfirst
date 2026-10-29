"""Container healthcheck: healthy while the worker loop keeps touching its heartbeat file.

Usage: python -m triage_worker.healthcheck   (exit 0 = healthy, 1 = stale or missing)
"""

import sys
import time
from pathlib import Path

from triage_core.settings import get_settings

GRACE_S = 10.0


def is_healthy(heartbeat_file: Path, poll_interval_s: float, now: float | None = None) -> bool:
    try:
        age = (now if now is not None else time.time()) - heartbeat_file.stat().st_mtime
    except FileNotFoundError:
        return False
    return age <= poll_interval_s * 3 + GRACE_S


if __name__ == "__main__":
    settings = get_settings()
    sys.exit(
        0 if is_healthy(settings.worker_heartbeat_file, settings.worker_poll_interval_s) else 1
    )

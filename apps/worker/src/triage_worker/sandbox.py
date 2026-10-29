"""Cloning untrusted repositories safely (plan section 8.1).

Repository code is only ever read, never executed: hooks are disabled, submodules and LFS
are skipped, and size/file-count limits are enforced before any scanner touches it.
"""

import re
import shutil
from pathlib import Path

import structlog

from triage_core.settings import Settings
from triage_worker.errors import PermanentJobError, TransientJobError
from triage_worker.process import ProcessTimeoutError, run

log = structlog.get_logger()

_FULL_NAME = re.compile(r"^[A-Za-z0-9-]{1,39}/[A-Za-z0-9._-]{1,100}$")
_BRANCH = re.compile(r"^[A-Za-z0-9._/-]{1,255}$")
_SKIP_DIRS = {".git"}

GIT_ENV = {
    "GIT_TERMINAL_PROMPT": "0",  # never wait for credentials (private/missing repos)
    "GIT_LFS_SKIP_SMUDGE": "1",
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_CONFIG_GLOBAL": "/dev/null",
}


def clone_args(full_name: str, branch: str, dest: Path) -> list[str]:
    if not _FULL_NAME.match(full_name):
        raise PermanentJobError(f"Invalid repository name: {full_name!r}")
    if not _BRANCH.match(branch) or branch.startswith("-") or ".." in branch:
        raise PermanentJobError(f"Unsupported branch name: {branch!r}")
    return [
        "git",
        "-c", "core.hooksPath=/dev/null",
        "-c", "protocol.file.allow=never",
        "clone",
        "--depth", "1",
        "--single-branch",
        "--branch", branch,
        "--no-tags",
        "--no-recurse-submodules",
        "--",
        # Built from the validated name, never from user input: no SSRF.
        f"https://github.com/{full_name}.git",
        str(dest),
    ]  # fmt: skip


async def clone(full_name: str, branch: str, dest: Path, settings: Settings) -> str:
    """Shallow-clones into dest and returns the commit SHA that was checked out.

    No blob filter: checkout would fetch filtered blobs on demand anyway. The clone timeout
    bounds the download and enforce_limits rejects oversized checkouts afterwards.
    """
    try:
        result = await run(
            clone_args(full_name, branch, dest),
            timeout_s=settings.scan_clone_timeout_s,
            env=GIT_ENV,
        )
    except ProcessTimeoutError:
        raise TransientJobError(
            f"Cloning took longer than {settings.scan_clone_timeout_s}s"
        ) from None
    if result.returncode != 0:
        stderr = result.stderr.lower()
        # Branch check first: git's message for a missing branch also says "not found".
        if "remote branch" in stderr and "not found" in stderr:
            raise PermanentJobError(f"Branch {branch!r} no longer exists")
        if "not found" in stderr or "could not read username" in stderr:
            raise PermanentJobError("Repository not found on GitHub, or it is no longer public")
        log.warning("clone.failed", stderr=result.stderr[-500:])
        raise TransientJobError("git clone failed")

    sha = await run(["git", "-C", str(dest), "rev-parse", "HEAD"], timeout_s=10, env=GIT_ENV)
    shutil.rmtree(dest / ".git", ignore_errors=True)  # scanners don't need history
    enforce_limits(dest, settings)
    return sha.stdout.strip()


def enforce_limits(root: Path, settings: Settings) -> None:
    """Rejects oversized checkouts and removes symlinks that point outside the clone."""
    max_bytes = settings.scan_max_repo_mb * 1024 * 1024
    total = files = 0
    resolved_root = root.resolve()
    for path in root.rglob("*"):
        if any(part in _SKIP_DIRS for part in path.relative_to(root).parts):
            continue
        if path.is_symlink():
            target = path.resolve()
            if not target.is_relative_to(resolved_root):
                path.unlink()
            continue
        if path.is_file():
            files += 1
            total += path.stat().st_size
            if files > settings.scan_max_files:
                raise PermanentJobError(
                    f"Repository has more than {settings.scan_max_files:,} files"
                )
            if total > max_bytes:
                raise PermanentJobError(f"Repository is larger than {settings.scan_max_repo_mb} MB")

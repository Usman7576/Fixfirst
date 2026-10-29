"""Scanner adapters: run a tool, then parse its JSON into triage_core Findings."""

from pathlib import Path, PurePosixPath

from triage_core.findings import MAX_SNIPPET_LINES
from triage_core.redaction import redact_secrets


def relative_path(path: str, root: Path) -> str | None:
    """Repo-relative POSIX path, or None if the tool reported something outside the clone."""
    # Scanners run in a Linux container and report POSIX paths, whatever OS runs the tests.
    posix = PurePosixPath(path.replace("\\", "/"))
    if posix.is_absolute():
        try:
            posix = posix.relative_to(PurePosixPath(root.resolve().as_posix()))
        except ValueError:
            return None
    if ".." in posix.parts:
        return None
    text = str(posix)
    return text[2:] if text.startswith("./") else text


def read_snippet(root: Path, rel_path: str, start: int, end: int) -> str | None:
    try:
        lines = (root / rel_path).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None
    end = min(end, start + MAX_SNIPPET_LINES - 1)
    return redact_secrets("\n".join(lines[start - 1 : end]))

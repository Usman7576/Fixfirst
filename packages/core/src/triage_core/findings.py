"""The single Finding shape both scanners are normalised into (plan section 8.3)."""

import re
from typing import Any

from pydantic import BaseModel, Field

from triage_core.domain import Severity, Tool

MAX_SNIPPET_LINES = 40

_TEST_PATH = re.compile(
    r"(^|/)(tests?|__tests__|spec|specs|testing|fixtures?|e2e|cypress)(/|$)"
    r"|(^|/)(test_[^/]+|[^/]+_test\.py|conftest\.py|[^/]+\.(test|spec)\.[jt]sx?)$",
    re.IGNORECASE,
)


def is_test_path(path: str) -> bool:
    return bool(_TEST_PATH.search(path))


class Finding(BaseModel):
    tool: Tool
    rule_id: str = Field(max_length=300)
    title: str = Field(max_length=300)
    cwe: list[str] = []
    file_path: str  # repo-relative, posix separators
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    snippet: str  # redacted, at most MAX_SNIPPET_LINES lines
    scanner_severity: Severity
    package: str | None = None  # OSV only
    installed_version: str | None = None
    fixed_version: str | None = None
    is_test_code: bool = False
    fingerprint: str = ""  # assigned by triage_core.fingerprint.assign_fingerprints
    raw: dict[str, Any] = {}


def title_from_message(message: str, fallback: str) -> str:
    """First sentence of a scanner message, trimmed to fit the issue title column."""
    text = " ".join(message.split())
    if not text:
        return fallback[:300]
    first = re.split(r"(?<=[.!?])\s", text, maxsplit=1)[0]
    return first if len(first) <= 300 else first[:297] + "..."


def normalise_cwe(values: Any) -> list[str]:
    """Scanner metadata says 'CWE-89: Improper Neutralization...'; keep just 'CWE-89'."""
    if isinstance(values, str):
        values = [values]
    if not isinstance(values, list):
        return []
    found: list[str] = []
    for value in values:
        match = re.search(r"CWE-\d+", str(value))
        if match and match.group(0) not in found:
            found.append(match.group(0))
    return found

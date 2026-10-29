"""Stable issue identity across scans (plan section 8.4, ADR 0005).

The fingerprint ignores line numbers, whitespace, comments and local variable names, so
editing code above a finding or renaming a variable doesn't turn it into a new issue.
"""

import hashlib
import re
from collections import Counter
from collections.abc import Iterable

from triage_core.domain import Tool
from triage_core.findings import Finding

FINGERPRINT_VERSION = 1
MAX_KEPT_STRING = 32

# Language keywords and common builtins stay verbatim: they carry the meaning of the code.
KEYWORDS = frozenset(
    """
    False None True and as assert async await break class continue def del elif else except
    finally for from global if import in is lambda nonlocal not or pass raise return try
    while with yield match case print open eval exec compile input format len str int bytes
    abstract arguments boolean catch const debugger default delete do export extends
    function implements instanceof interface let new null package private protected public
    static super switch this throw typeof undefined var void require module exports document
    window
    """.split()  # noqa: SIM905  (a word list reads better than 90 quoted items)
)

_TOKEN = re.compile(
    r"""
    (?P<comment>\#[^\n]*|//[^\n]*|/\*[\s\S]*?\*/)
  | (?P<string>"(?:\\.|[^"\\\n])*"|'(?:\\.|[^'\\\n])*'|`(?:\\.|[^`\\])*`)
  | (?P<ident>[A-Za-z_$][A-Za-z0-9_$]*)
  | (?P<number>\d[\w.]*)
  | (?P<space>\s+)
  | (?P<other>.)
    """,
    re.VERBOSE,
)


def normalise_snippet(code: str) -> str:
    """Token stream with comments/whitespace dropped and identifiers numbered by first use.

    Attribute names after '.' are kept (`req.query` and `req.body` are different findings).
    """
    names: dict[str, str] = {}
    out: list[str] = []
    previous = ""
    for match in _TOKEN.finditer(code):
        kind, text = match.lastgroup, match.group()
        if kind in ("comment", "space"):
            continue
        if kind == "ident":
            if text in KEYWORDS or previous == ".":
                token = text
            else:
                token = names.setdefault(text, f"v{len(names) + 1}")
        elif kind == "string":
            body = text[1:-1]
            token = text if len(body) <= MAX_KEPT_STRING else f"{text[0]}<str>{text[-1]}"
        else:
            token = text
        out.append(token)
        previous = token
    return " ".join(out)


def _sha256(*parts: str) -> str:
    return hashlib.sha256("\x1f".join(parts).encode()).hexdigest()


def code_fingerprint(rule_id: str, file_path: str, snippet: str, occurrence: int) -> str:
    return _sha256(rule_id, file_path, normalise_snippet(snippet), str(occurrence))


def dependency_fingerprint(vuln_id: str, package: str, manifest_path: str) -> str:
    # Version excluded: bumping to another still-vulnerable version is the same issue.
    return _sha256("osv", vuln_id, package, manifest_path)


def assign_fingerprints(findings: Iterable[Finding]) -> list[Finding]:
    """Sets each finding's fingerprint. Identical code matches in one file get an
    occurrence index (ordered by position) so they stay distinct issues."""
    unique: dict[tuple[object, ...], Finding] = {}
    for finding in findings:
        # Scanners occasionally report the very same hit twice (e.g. overlapping rule files).
        key = (
            finding.tool,
            finding.rule_id,
            finding.file_path,
            finding.start_line,
            finding.end_line,
            finding.package,
        )
        unique.setdefault(key, finding)
    ordered = sorted(unique.values(), key=lambda f: (f.file_path, f.start_line, f.rule_id))
    seen: Counter[str] = Counter()
    for finding in ordered:
        if finding.tool is Tool.OSV:
            finding.fingerprint = dependency_fingerprint(
                finding.rule_id, finding.package or "", finding.file_path
            )
            continue
        base = code_fingerprint(finding.rule_id, finding.file_path, finding.snippet, 0)
        finding.fingerprint = (
            base
            if seen[base] == 0
            else code_fingerprint(finding.rule_id, finding.file_path, finding.snippet, seen[base])
        )
        seen[base] += 1
    return ordered

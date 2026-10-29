"""Semgrep CE: static analysis of first-party code with vendored, pinned rules."""

import json
from pathlib import Path
from typing import Any

import structlog

from triage_core.domain import Severity, Tool
from triage_core.findings import Finding, is_test_path, normalise_cwe, title_from_message
from triage_core.redaction import redact_secrets
from triage_core.settings import Settings
from triage_worker.errors import TransientJobError
from triage_worker.process import ProcessTimeoutError, run
from triage_worker.scanners import read_snippet, relative_path

log = structlog.get_logger()

EXCLUDES = (
    "node_modules", "vendor", "dist", "build", ".next", "coverage", "bower_components",
    "*.min.js", "*.bundle.js", "*.map",
)  # fmt: skip

_SEVERITY = {
    "CRITICAL": Severity.CRITICAL,
    "ERROR": Severity.HIGH,
    "HIGH": Severity.HIGH,
    "WARNING": Severity.MEDIUM,
    "MEDIUM": Severity.MEDIUM,
    "INFO": Severity.LOW,
    "LOW": Severity.LOW,
}


def semgrep_args(settings: Settings) -> list[str]:
    args = [
        settings.semgrep_bin, "scan",
        "--config", str(settings.semgrep_rules_dir),
        "--json",
        "--metrics=off",
        "--disable-version-check",
        "--timeout", "30",
        "--max-target-bytes", "1000000",
        "--jobs", "2",
    ]  # fmt: skip
    for pattern in EXCLUDES:
        args += ["--exclude", pattern]
    return [*args, "."]


async def run_semgrep(src: Path, settings: Settings) -> dict[str, Any]:
    try:
        result = await run(
            semgrep_args(settings),
            cwd=src,
            timeout_s=settings.scan_timeout_s,
            env={"SEMGREP_SEND_METRICS": "off", "SEMGREP_ENABLE_VERSION_CHECK": "0"},
        )
    except ProcessTimeoutError as exc:
        raise TransientJobError(f"Semgrep: {exc}") from None
    # 0 = ran (with or without findings); anything else is a crash or bad config.
    if result.returncode != 0:
        log.error("semgrep.failed", code=result.returncode, stderr=result.stderr[-1000:])
        raise TransientJobError(f"Semgrep exited with code {result.returncode}")
    data: dict[str, Any] = json.loads(result.stdout)
    if data.get("errors"):
        log.info("semgrep.partial_errors", count=len(data["errors"]))
    return data


def rule_id(check_id: str, rules_dir: Path) -> str:
    """Strips the install-path prefix so rule ids (and so fingerprints) don't depend on where
    the rules are installed: 'opt.semgrep-rules.python.x.y' -> 'python.x.y'."""
    prefix = ".".join(p for p in rules_dir.parts if p not in ("/", "\\")) + "."
    return check_id.removeprefix(prefix)


def _severity(extra: dict[str, Any]) -> Severity:
    severity = _SEVERITY.get(str(extra.get("severity", "")).upper(), Severity.MEDIUM)
    metadata = extra.get("metadata") or {}
    if (
        severity is Severity.HIGH
        and str(metadata.get("impact", "")).upper() == "HIGH"
        and str(metadata.get("likelihood", "")).upper() == "HIGH"
    ):
        return Severity.CRITICAL
    return severity


def parse_semgrep(data: dict[str, Any], root: Path, rules_dir: Path) -> list[Finding]:
    findings: list[Finding] = []
    for result in data.get("results", []):
        path = relative_path(result["path"], root)
        if path is None:
            continue
        extra = result.get("extra") or {}
        start, end = int(result["start"]["line"]), int(result["end"]["line"])
        snippet = read_snippet(root, path, start, end)
        if snippet is None:
            # Semgrep's own copy reads "requires login" for anonymous runs; last resort only.
            snippet = redact_secrets(str(extra.get("lines", "")))
        check_id = rule_id(result["check_id"], rules_dir)
        metadata = extra.get("metadata") or {}
        findings.append(
            Finding(
                tool=Tool.SEMGREP,
                rule_id=check_id[:300],
                title=title_from_message(str(extra.get("message", "")), check_id),
                cwe=normalise_cwe(metadata.get("cwe")),
                file_path=path,
                start_line=start,
                end_line=max(end, start),
                snippet=snippet,
                scanner_severity=_severity(extra),
                is_test_code=is_test_path(path),
                raw={
                    "check_id": check_id,
                    "message": extra.get("message"),
                    "severity": extra.get("severity"),
                    "metadata": {
                        k: metadata[k]
                        for k in ("category", "confidence", "impact", "likelihood", "owasp")
                        if k in metadata
                    },
                },
            )
        )
    return findings

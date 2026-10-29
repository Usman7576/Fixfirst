"""OSV-Scanner: known vulnerabilities in dependencies, read from lockfiles."""

import json
from pathlib import Path
from typing import Any

import structlog

from triage_core.domain import Severity, Tool
from triage_core.findings import Finding, is_test_path, normalise_cwe
from triage_core.settings import Settings
from triage_worker.errors import TransientJobError
from triage_worker.process import ProcessTimeoutError, run
from triage_worker.scanners import relative_path

log = structlog.get_logger()

EXIT_OK, EXIT_VULNS_FOUND, EXIT_NO_PACKAGES = 0, 1, 128

_LABEL_SEVERITY = {
    "CRITICAL": Severity.CRITICAL,
    "HIGH": Severity.HIGH,
    "MODERATE": Severity.MEDIUM,
    "MEDIUM": Severity.MEDIUM,
    "LOW": Severity.LOW,
}


async def run_osv(src: Path, settings: Settings) -> dict[str, Any]:
    args = [settings.osv_scanner_bin, "scan", "source", "--recursive", "--format", "json", "."]
    try:
        result = await run(args, cwd=src, timeout_s=settings.scan_timeout_s)
    except ProcessTimeoutError as exc:
        raise TransientJobError(f"OSV-Scanner: {exc}") from None
    if result.returncode == EXIT_NO_PACKAGES:
        return {"results": []}
    if result.returncode not in (EXIT_OK, EXIT_VULNS_FOUND):
        log.error("osv.failed", code=result.returncode, stderr=result.stderr[-1000:])
        raise TransientJobError(f"OSV-Scanner exited with code {result.returncode}")
    data: dict[str, Any] = json.loads(result.stdout or '{"results": []}')
    return data


def _severity(group: dict[str, Any], vuln: dict[str, Any]) -> Severity:
    try:
        score = float(group.get("max_severity") or "")
    except ValueError:
        label = str((vuln.get("database_specific") or {}).get("severity", "")).upper()
        return _LABEL_SEVERITY.get(label, Severity.MEDIUM)
    if score >= 9.0:
        return Severity.CRITICAL
    if score >= 7.0:
        return Severity.HIGH
    if score >= 4.0:
        return Severity.MEDIUM
    return Severity.LOW


def _primary_id(ids: list[str]) -> str:
    """One stable id per alias group (GHSA, then CVE, then anything), for the fingerprint."""
    for prefix in ("GHSA-", "CVE-"):
        matches = sorted(i for i in ids if i.startswith(prefix))
        if matches:
            return matches[0]
    return sorted(ids)[0]


def _fixed_version(vuln: dict[str, Any], package: str) -> str | None:
    for affected in vuln.get("affected", []):
        if (affected.get("package") or {}).get("name") != package:
            continue
        for range_ in affected.get("ranges", []):
            for event in range_.get("events", []):
                if "fixed" in event:
                    return str(event["fixed"])
    return None


def _manifest_line(root: Path, rel_path: str, package: str) -> tuple[int, str]:
    try:
        for number, line in enumerate((root / rel_path).read_text(errors="replace").splitlines()):
            if f'"{package}"' in line or line.strip().startswith(f"{package}=="):
                return number + 1, line.strip()[:300]
    except OSError:
        pass
    return 1, package


def parse_osv(data: dict[str, Any], root: Path) -> list[Finding]:
    findings: list[Finding] = []
    for result in data.get("results") or []:
        manifest = relative_path((result.get("source") or {}).get("path", ""), root)
        if not manifest:
            continue
        for entry in result.get("packages") or []:
            package = entry.get("package") or {}
            name, version = str(package.get("name", "")), str(package.get("version", ""))
            vulns = {v["id"]: v for v in entry.get("vulnerabilities") or []}
            groups = entry.get("groups") or [{"ids": [vid]} for vid in vulns]
            for group in groups:
                ids = [i for i in group.get("ids", []) if i in vulns] or group.get("ids", [])
                if not ids:
                    continue
                primary = _primary_id(ids)
                vuln: dict[str, Any] = vulns.get(primary) or next(iter(vulns.values()), {})
                line, snippet = _manifest_line(root, manifest, name)
                summary = vuln.get("summary") or vuln.get("details", "")[:200] or primary
                findings.append(
                    Finding(
                        tool=Tool.OSV,
                        rule_id=primary,
                        title=f"{name} {version}: {summary}"[:300],
                        cwe=normalise_cwe((vuln.get("database_specific") or {}).get("cwe_ids")),
                        file_path=manifest,
                        start_line=line,
                        end_line=line,
                        snippet=snippet,
                        scanner_severity=_severity(group, vuln),
                        package=name,
                        installed_version=version,
                        fixed_version=_fixed_version(vuln, name),
                        is_test_code=is_test_path(manifest),
                        raw={"ids": ids, "ecosystem": package.get("ecosystem")},
                    )
                )
    return findings

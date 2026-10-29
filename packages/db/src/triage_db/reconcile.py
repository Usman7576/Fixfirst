"""Turns a scan's findings into issue state (plan sections 4.1 and 8.5).

- New fingerprint             -> new Open issue
- Seen again                  -> last_seen_scan updated (Fixed ones are reopened)
- Missing after a FULL scan   -> Open/In-progress issues become Fixed
Human decisions (False positive, Accepted risk) are never changed here.
"""

from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from triage_core.domain import IssueStatus
from triage_core.findings import Finding
from triage_core.fingerprint import FINGERPRINT_VERSION
from triage_db import audit
from triage_db.models import Finding as FindingRow
from triage_db.models import Issue, Repository, Scan

AUTO_CLOSABLE = (IssueStatus.OPEN, IssueStatus.IN_PROGRESS)


@dataclass(frozen=True)
class ReconcileResult:
    raw_count: int
    issue_count: int
    new: int
    reopened: int
    fixed: int


async def reconcile(
    session: AsyncSession, scan: Scan, findings: list[Finding], *, full_scan: bool
) -> ReconcileResult:
    """Idempotent for a given scan: a retried job deletes its earlier findings first.
    Runs inside the caller's transaction; the caller commits."""
    await session.execute(delete(FindingRow).where(FindingRow.scan_id == scan.id))

    by_fingerprint: dict[str, list[Finding]] = defaultdict(list)
    for finding in findings:
        by_fingerprint[finding.fingerprint].append(finding)

    existing = {
        issue.fingerprint: issue
        for issue in await session.scalars(
            select(Issue).where(
                Issue.repo_id == scan.repo_id, Issue.fingerprint.in_(list(by_fingerprint))
            )
        )
    }
    new = reopened = 0
    issues: dict[str, Issue] = {}
    for fingerprint, group in by_fingerprint.items():
        first = group[0]
        issue = existing.get(fingerprint)
        if issue is None:
            issue = Issue(
                repo_id=scan.repo_id,
                fingerprint=fingerprint,
                fingerprint_version=FINGERPRINT_VERSION,
                tool=first.tool,
                rule_id=first.rule_id,
                status=IssueStatus.OPEN,
                first_seen_scan=scan.id,
            )
            session.add(issue)
            new += 1
        elif issue.status is IssueStatus.FIXED:
            issue.status = IssueStatus.OPEN
            issue.reopened_count += 1
            reopened += 1
        issue.title = first.title
        issue.cwe = first.cwe
        issue.last_seen_scan = scan.id
        issues[fingerprint] = issue
    await session.flush()

    session.add_all(
        FindingRow(
            scan_id=scan.id,
            issue_id=issues[f.fingerprint].id,
            tool=f.tool,
            rule_id=f.rule_id,
            file_path=f.file_path,
            start_line=f.start_line,
            end_line=f.end_line,
            snippet=f.snippet,
            scanner_severity=f.scanner_severity,
            fingerprint=f.fingerprint,
            raw={
                **f.raw,
                "is_test_code": f.is_test_code,
                "package": f.package,
                "installed_version": f.installed_version,
                "fixed_version": f.fixed_version,
            },
        )
        for f in findings
    )

    fixed = 0
    if full_scan:
        # Only a successful full scan may close issues; a partial one would look like a fix.
        result = await session.execute(
            update(Issue)
            .where(
                Issue.repo_id == scan.repo_id,
                Issue.status.in_(AUTO_CLOSABLE),
                Issue.last_seen_scan != scan.id,
            )
            .values(status=IssueStatus.FIXED)
            .returning(Issue.id)
        )
        fixed = len(result.all())

    team_id = await session.scalar(select(Repository.team_id).where(Repository.id == scan.repo_id))
    audit.record(
        session,
        action="scan.reconciled",
        entity="scan",
        entity_id=scan.id,
        team_id=team_id,
        user_id=None,  # system action
        after={"new": new, "reopened": reopened, "fixed": fixed, "findings": len(findings)},
    )
    return ReconcileResult(
        raw_count=len(findings),
        issue_count=len(issues),
        new=new,
        reopened=reopened,
        fixed=fixed,
    )

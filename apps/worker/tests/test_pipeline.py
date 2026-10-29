"""Scan pipeline against Postgres with fake clone/scanner: issue lifecycle across rescans."""

import uuid
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from triage_core.domain import IssueStatus, ScanKind, ScanStatus, Severity, Tool
from triage_core.findings import Finding
from triage_core.settings import Settings
from triage_db.models import AuditLog, Issue, Repository, Scan, Team
from triage_db.models import Finding as FindingRow
from triage_worker.errors import PermanentJobError
from triage_worker.handlers import ScanTools, run_scan

pytestmark = pytest.mark.integration

Sessions = async_sessionmaker[AsyncSession]

SQLI = 'db.query("SELECT * FROM users WHERE id = " + req.query.id)'
XSS = "res.send(req.query.name)"
EVAL = "eval(req.body.code)"


def _hit(snippet: str, path: str = "routes/user.js", line: int = 10, rule: str = "") -> Finding:
    return Finding(
        tool=Tool.SEMGREP,
        rule_id=rule or f"js.{snippet[:4]}",
        title=f"Problem in {snippet[:10]}",
        file_path=path,
        start_line=line,
        end_line=line,
        snippet=snippet,
        scanner_severity=Severity.HIGH,
    )


class FakeRepo:
    """Stands in for git + scanners; tests set what the next scan 'finds'."""

    def __init__(self) -> None:
        self.findings: list[Finding] = []
        self.cloned_into: list[Path] = []

    async def clone(self, full_name: str, branch: str, dest: Path, settings: Settings) -> str:
        dest.mkdir(parents=True)
        (dest / "app.js").write_text("// code")
        self.cloned_into.append(dest)
        return "a" * 40

    async def scan(self, src: Path, settings: Settings) -> list[Finding]:
        return [f.model_copy() for f in self.findings]

    @property
    def tools(self) -> ScanTools:
        return ScanTools(clone=self.clone, scan=self.scan)


@pytest.fixture
def fake() -> FakeRepo:
    return FakeRepo()


@pytest.fixture
def scan_settings(settings: Settings, tmp_path: Path) -> Settings:
    return settings.model_copy(update={"scan_work_dir": tmp_path / "work"})


@pytest.fixture
async def repo_id(sessions: Sessions) -> uuid.UUID:
    async with sessions() as session:
        team = Team(name="t")
        session.add(team)
        await session.flush()
        repo = Repository(
            team_id=team.id,
            github_repo_id=1,
            github_full_name="acme/app",
            default_branch="main",
            is_private=False,
        )
        session.add(repo)
        await session.commit()
        return repo.id


async def _scan(
    sessions: Sessions,
    repo_id: uuid.UUID,
    settings: Settings,
    fake: FakeRepo,
    kind: ScanKind = ScanKind.FULL,
) -> Scan:
    async with sessions() as session:
        scan = Scan(repo_id=repo_id, kind=kind)
        session.add(scan)
        await session.commit()
    await run_scan(sessions, {"scan_id": str(scan.id)}, settings, fake.tools)
    async with sessions() as session:
        result = await session.get(Scan, scan.id)
        assert result is not None
        return result


async def _issues(sessions: Sessions) -> dict[str, Issue]:
    async with sessions() as session:
        return {i.title: i for i in await session.scalars(select(Issue))}


async def test_first_scan_creates_issues_and_findings(
    sessions: Sessions, repo_id: uuid.UUID, scan_settings: Settings, fake: FakeRepo
) -> None:
    fake.findings = [_hit(SQLI), _hit(XSS, line=20), _hit(SQLI, path="routes/admin.js")]

    scan = await _scan(sessions, repo_id, scan_settings, fake)

    assert scan.status is ScanStatus.DONE
    assert scan.commit_sha == "a" * 40
    assert (scan.raw_count, scan.issue_count) == (3, 3)
    assert scan.progress["stage"] == "done"
    assert scan.progress["new"] == 3
    issues = await _issues(sessions)
    assert all(i.status is IssueStatus.OPEN for i in issues.values())
    async with sessions() as session:
        assert await session.scalar(select(func.count()).select_from(FindingRow)) == 3
        repo = await session.get(Repository, repo_id)
        assert repo is not None
        assert repo.last_scanned_at is not None


async def test_rescan_of_unchanged_code_keeps_the_same_issues(
    sessions: Sessions, repo_id: uuid.UUID, scan_settings: Settings, fake: FakeRepo
) -> None:
    fake.findings = [_hit(SQLI), _hit(XSS, line=20)]
    first = await _scan(sessions, repo_id, scan_settings, fake)
    before = {t: i.id for t, i in (await _issues(sessions)).items()}

    # Same code, shifted down by 30 lines: identity must survive.
    fake.findings = [_hit(SQLI, line=40), _hit(XSS, line=50)]
    second = await _scan(sessions, repo_id, scan_settings, fake)

    after = await _issues(sessions)
    assert {t: i.id for t, i in after.items()} == before
    assert all(i.first_seen_scan == first.id for i in after.values())
    assert all(i.last_seen_scan == second.id for i in after.values())
    assert second.progress["new"] == 0


async def test_finding_missing_from_full_rescan_is_marked_fixed(
    sessions: Sessions, repo_id: uuid.UUID, scan_settings: Settings, fake: FakeRepo
) -> None:
    fake.findings = [_hit(SQLI), _hit(XSS, line=20)]
    await _scan(sessions, repo_id, scan_settings, fake)

    fake.findings = [_hit(XSS, line=20)]  # the SQL injection was fixed
    scan = await _scan(sessions, repo_id, scan_settings, fake)

    issues = await _issues(sessions)
    assert issues[f"Problem in {SQLI[:10]}"].status is IssueStatus.FIXED
    assert issues[f"Problem in {XSS[:10]}"].status is IssueStatus.OPEN
    assert scan.progress["fixed"] == 1


async def test_incremental_scan_never_closes_issues(
    sessions: Sessions, repo_id: uuid.UUID, scan_settings: Settings, fake: FakeRepo
) -> None:
    fake.findings = [_hit(SQLI)]
    await _scan(sessions, repo_id, scan_settings, fake)

    fake.findings = []
    await _scan(sessions, repo_id, scan_settings, fake, kind=ScanKind.INCREMENTAL)

    [issue] = (await _issues(sessions)).values()
    assert issue.status is IssueStatus.OPEN


async def test_fixed_issue_that_reappears_is_reopened(
    sessions: Sessions, repo_id: uuid.UUID, scan_settings: Settings, fake: FakeRepo
) -> None:
    fake.findings = [_hit(SQLI)]
    await _scan(sessions, repo_id, scan_settings, fake)
    fake.findings = []
    await _scan(sessions, repo_id, scan_settings, fake)

    fake.findings = [_hit(SQLI)]
    scan = await _scan(sessions, repo_id, scan_settings, fake)

    [issue] = (await _issues(sessions)).values()
    assert issue.status is IssueStatus.OPEN
    assert issue.reopened_count == 1
    assert scan.progress["reopened"] == 1


@pytest.mark.parametrize("decision", [IssueStatus.FALSE_POSITIVE, IssueStatus.ACCEPTED_RISK])
async def test_human_decisions_survive_rescans(
    sessions: Sessions,
    repo_id: uuid.UUID,
    scan_settings: Settings,
    fake: FakeRepo,
    decision: IssueStatus,
) -> None:
    fake.findings = [_hit(SQLI)]
    await _scan(sessions, repo_id, scan_settings, fake)
    async with sessions() as session:
        await session.execute(update(Issue).values(status=decision))
        await session.commit()

    await _scan(sessions, repo_id, scan_settings, fake)  # still present
    fake.findings = []
    await _scan(sessions, repo_id, scan_settings, fake)  # now gone

    [issue] = (await _issues(sessions)).values()
    assert issue.status is decision


async def test_reconciliation_is_audit_logged_as_a_system_action(
    sessions: Sessions, repo_id: uuid.UUID, scan_settings: Settings, fake: FakeRepo
) -> None:
    fake.findings = [_hit(SQLI)]
    await _scan(sessions, repo_id, scan_settings, fake)

    async with sessions() as session:
        entry = await session.scalar(select(AuditLog).where(AuditLog.action == "scan.reconciled"))
    assert entry is not None
    assert entry.user_id is None
    assert entry.after == {"new": 1, "reopened": 0, "fixed": 0, "findings": 1}


async def test_workdir_is_removed_even_when_scanning_fails(
    sessions: Sessions, repo_id: uuid.UUID, scan_settings: Settings, fake: FakeRepo
) -> None:
    async def broken_scan(src: Path, settings: Settings) -> list[Finding]:
        raise RuntimeError("semgrep crashed")

    async with sessions() as session:
        scan = Scan(repo_id=repo_id)
        session.add(scan)
        await session.commit()

    with pytest.raises(RuntimeError):
        await run_scan(
            sessions,
            {"scan_id": str(scan.id)},
            scan_settings,
            ScanTools(clone=fake.clone, scan=broken_scan),
        )

    assert fake.cloned_into
    assert not fake.cloned_into[0].parent.exists()


async def test_disconnected_repository_fails_permanently(
    sessions: Sessions, repo_id: uuid.UUID, scan_settings: Settings, fake: FakeRepo
) -> None:
    async with sessions() as session:
        scan = Scan(repo_id=repo_id)
        session.add(scan)
        await session.execute(
            update(Repository).values(deleted_at=func.now()).where(Repository.id == repo_id)
        )
        await session.commit()

    with pytest.raises(PermanentJobError, match="disconnected"):
        await run_scan(sessions, {"scan_id": str(scan.id)}, scan_settings, fake.tools)


async def test_retried_scan_does_not_duplicate_findings(
    sessions: Sessions, repo_id: uuid.UUID, scan_settings: Settings, fake: FakeRepo
) -> None:
    fake.findings = [_hit(SQLI), _hit(XSS, line=20)]
    scan = await _scan(sessions, repo_id, scan_settings, fake)
    # Simulate a crash after reconcile but before the job was marked complete.
    async with sessions() as session:
        await session.execute(
            update(Scan).where(Scan.id == scan.id).values(status=ScanStatus.RUNNING)
        )
        await session.commit()

    await run_scan(sessions, {"scan_id": str(scan.id)}, scan_settings, fake.tools)

    async with sessions() as session:
        count: Any = await session.scalar(select(func.count()).select_from(FindingRow))
    assert count == 2

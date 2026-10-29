"""ORM models for every MVP and v2 table (plan section 11)."""

import uuid
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy import BigInteger, ForeignKey, Index, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from triage_core.domain import (
    Exposure,
    FeedbackLabel,
    IssueStatus,
    JobStatus,
    PriorityBucket,
    Role,
    ScanKind,
    ScanStatus,
    Severity,
    Tool,
    Verdict,
)
from triage_db.base import Base, CreatedAt, UUIDPk, pg_enum

ROLE = pg_enum(Role, "role")
SCAN_KIND = pg_enum(ScanKind, "scan_kind")
SCAN_STATUS = pg_enum(ScanStatus, "scan_status")
JOB_STATUS = pg_enum(JobStatus, "job_status")
TOOL = pg_enum(Tool, "tool")
SEVERITY = pg_enum(Severity, "severity")
VERDICT = pg_enum(Verdict, "verdict")
EXPOSURE = pg_enum(Exposure, "exposure")
PRIORITY_BUCKET = pg_enum(PriorityBucket, "priority_bucket")
ISSUE_STATUS = pg_enum(IssueStatus, "issue_status")
FEEDBACK_LABEL = pg_enum(FeedbackLabel, "feedback_label")

# Literal SQL for the partial index; test_models checks it matches ACTIVE_SCAN_STATUSES.
ACTIVE_SCAN_PREDICATE = "status IN ('queued', 'running', 'waiting_quota')"


def _fk(target: str, *, nullable: bool = False, cascade: bool = True) -> Any:
    return mapped_column(
        ForeignKey(target, ondelete="CASCADE" if cascade else "SET NULL"),
        nullable=nullable,
        index=True,
    )


class User(UUIDPk, CreatedAt, Base):
    __tablename__ = "users"

    github_id: Mapped[int] = mapped_column(BigInteger, unique=True)
    login: Mapped[str] = mapped_column(String(100))
    name: Mapped[str | None] = mapped_column(String(255))
    email: Mapped[str | None] = mapped_column(String(320))
    avatar_url: Mapped[str | None] = mapped_column(String(500))
    # GitHub OAuth token, Fernet-encrypted (triage_core.crypto). Never logged or returned.
    gh_token_enc: Mapped[bytes | None]
    last_login_at: Mapped[datetime | None]

    memberships: Mapped[list["Membership"]] = relationship(back_populates="user")


class Team(UUIDPk, CreatedAt, Base):
    __tablename__ = "teams"

    name: Mapped[str] = mapped_column(String(100))
    slack_webhook_enc: Mapped[bytes | None]

    memberships: Mapped[list["Membership"]] = relationship(back_populates="team")


class Membership(CreatedAt, Base):
    __tablename__ = "memberships"

    team_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("teams.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    role: Mapped[Role] = mapped_column(ROLE)

    team: Mapped[Team] = relationship(back_populates="memberships")
    user: Mapped[User] = relationship(back_populates="memberships")


class Repository(UUIDPk, CreatedAt, Base):
    __tablename__ = "repositories"
    __table_args__ = (UniqueConstraint("team_id", "github_repo_id"),)

    team_id: Mapped[uuid.UUID] = _fk("teams.id")
    github_repo_id: Mapped[int] = mapped_column(BigInteger)
    github_full_name: Mapped[str] = mapped_column(String(200))
    default_branch: Mapped[str] = mapped_column(String(255))
    language: Mapped[str | None] = mapped_column(String(50))
    is_private: Mapped[bool]
    last_scanned_at: Mapped[datetime | None]
    deleted_at: Mapped[datetime | None]


class Scan(UUIDPk, CreatedAt, Base):
    __tablename__ = "scans"
    __table_args__ = (
        Index("ix_scans_repo_id_created_at", "repo_id", "created_at"),
        # At most one queued/running/paused scan per repository.
        Index(
            "uq_scans_one_active_per_repo",
            "repo_id",
            unique=True,
            postgresql_where=sa.text(ACTIVE_SCAN_PREDICATE),
        ),
    )

    repo_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("repositories.id", ondelete="CASCADE"))
    commit_sha: Mapped[str | None] = mapped_column(String(40))
    kind: Mapped[ScanKind] = mapped_column(SCAN_KIND, default=ScanKind.FULL)
    status: Mapped[ScanStatus] = mapped_column(SCAN_STATUS, default=ScanStatus.QUEUED)
    stage: Mapped[str | None] = mapped_column(String(50))
    progress: Mapped[dict[str, Any]] = mapped_column(default=dict, server_default="{}")
    started_at: Mapped[datetime | None]
    finished_at: Mapped[datetime | None]
    raw_count: Mapped[int] = mapped_column(default=0, server_default="0")
    issue_count: Mapped[int] = mapped_column(default=0, server_default="0")
    fix_now_count: Mapped[int] = mapped_column(default=0, server_default="0")
    llm_calls: Mapped[int] = mapped_column(default=0, server_default="0")
    tokens_in: Mapped[int] = mapped_column(default=0, server_default="0")
    tokens_out: Mapped[int] = mapped_column(default=0, server_default="0")
    failure_reason: Mapped[str | None] = mapped_column(Text)
    triggered_by: Mapped[uuid.UUID | None] = _fk("users.id", nullable=True, cascade=False)


class Issue(UUIDPk, CreatedAt, Base):
    __tablename__ = "issues"
    __table_args__ = (
        UniqueConstraint("repo_id", "fingerprint"),
        Index("ix_issues_repo_id_bucket_status", "repo_id", "priority_bucket", "status"),
    )

    repo_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("repositories.id", ondelete="CASCADE"))
    fingerprint: Mapped[str] = mapped_column(String(64))
    fingerprint_version: Mapped[int] = mapped_column(default=1, server_default="1")
    title: Mapped[str] = mapped_column(String(300))
    cwe: Mapped[list[str]] = mapped_column(sa.ARRAY(String(20)), default=list, server_default="{}")
    tool: Mapped[Tool] = mapped_column(TOOL)
    rule_id: Mapped[str] = mapped_column(String(300))
    verdict: Mapped[Verdict | None] = mapped_column(VERDICT)
    confidence: Mapped[float | None]
    exploitability: Mapped[float | None]
    exposure: Mapped[Exposure | None] = mapped_column(EXPOSURE)
    priority_score: Mapped[float | None]
    priority_bucket: Mapped[PriorityBucket | None] = mapped_column(PRIORITY_BUCKET)
    score_inputs: Mapped[dict[str, Any] | None]
    explanation: Mapped[str | None] = mapped_column(Text)
    attack_scenario: Mapped[str | None] = mapped_column(Text)
    fix_suggestion: Mapped[str | None] = mapped_column(Text)
    model_used: Mapped[str | None] = mapped_column(String(100))
    prompt_version: Mapped[str | None] = mapped_column(String(50))
    injection_suspected: Mapped[bool] = mapped_column(default=False, server_default="false")
    status: Mapped[IssueStatus] = mapped_column(ISSUE_STATUS, default=IssueStatus.OPEN)
    assignee_id: Mapped[uuid.UUID | None] = _fk("users.id", nullable=True, cascade=False)
    first_seen_scan: Mapped[uuid.UUID] = mapped_column(ForeignKey("scans.id"))
    last_seen_scan: Mapped[uuid.UUID] = mapped_column(ForeignKey("scans.id"))
    reopened_count: Mapped[int] = mapped_column(default=0, server_default="0")
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class Finding(UUIDPk, CreatedAt, Base):
    __tablename__ = "findings"

    scan_id: Mapped[uuid.UUID] = _fk("scans.id")
    issue_id: Mapped[uuid.UUID | None] = _fk("issues.id", nullable=True, cascade=False)
    tool: Mapped[Tool] = mapped_column(TOOL)
    rule_id: Mapped[str] = mapped_column(String(300))
    file_path: Mapped[str] = mapped_column(String(1000))
    start_line: Mapped[int]
    end_line: Mapped[int]
    snippet: Mapped[str] = mapped_column(Text)
    scanner_severity: Mapped[Severity] = mapped_column(SEVERITY)
    fingerprint: Mapped[str] = mapped_column(String(64))
    raw: Mapped[dict[str, Any]]


class VerdictCache(CreatedAt, Base):
    __tablename__ = "verdict_cache"

    cache_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    verdict: Mapped[dict[str, Any]]
    model_used: Mapped[str] = mapped_column(String(100))
    prompt_version: Mapped[str] = mapped_column(String(50))


class Job(UUIDPk, CreatedAt, Base):
    __tablename__ = "jobs"
    __table_args__ = (
        Index(
            "ix_jobs_ready",
            "priority",
            "run_after",
            postgresql_where=sa.text("status = 'queued'"),
        ),
        Index(
            "ix_jobs_running_lease", "lease_until", postgresql_where=sa.text("status = 'running'")
        ),
    )

    kind: Mapped[str] = mapped_column(String(50))
    payload: Mapped[dict[str, Any]]
    status: Mapped[JobStatus] = mapped_column(JOB_STATUS, default=JobStatus.QUEUED)
    priority: Mapped[int] = mapped_column(default=0, server_default="0")
    attempts: Mapped[int] = mapped_column(default=0, server_default="0")
    max_attempts: Mapped[int] = mapped_column(default=3, server_default="3")
    run_after: Mapped[datetime] = mapped_column(server_default=func.now())
    lease_until: Mapped[datetime | None]
    locked_by: Mapped[str | None] = mapped_column(String(200))
    last_error: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class Feedback(UUIDPk, CreatedAt, Base):
    __tablename__ = "feedback"

    issue_id: Mapped[uuid.UUID] = _fk("issues.id")
    user_id: Mapped[uuid.UUID | None] = _fk("users.id", nullable=True, cascade=False)
    label: Mapped[FeedbackLabel] = mapped_column(FEEDBACK_LABEL)
    reason: Mapped[str] = mapped_column(Text)


class AuditLog(UUIDPk, CreatedAt, Base):
    __tablename__ = "audit_log"
    __table_args__ = (Index("ix_audit_log_team_id_created_at", "team_id", "created_at"),)

    team_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"))
    # Null user = action taken by the system (e.g. auto-Fixed on rescan).
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    action: Mapped[str] = mapped_column(String(100))
    entity: Mapped[str] = mapped_column(String(50))
    entity_id: Mapped[str | None] = mapped_column(String(100))
    before: Mapped[dict[str, Any] | None]
    after: Mapped[dict[str, Any] | None]
    ip: Mapped[str | None] = mapped_column(String(64))
    request_id: Mapped[str | None] = mapped_column(String(64))


class RefreshToken(UUIDPk, CreatedAt, Base):
    __tablename__ = "refresh_tokens"

    user_id: Mapped[uuid.UUID] = _fk("users.id")
    # SHA-256 of the opaque token; the token itself only ever lives in the user's cookie.
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    family_id: Mapped[uuid.UUID] = mapped_column(index=True)
    expires_at: Mapped[datetime]
    revoked_at: Mapped[datetime | None]


class RateLimit(Base):
    __tablename__ = "rate_limits"

    provider: Mapped[str] = mapped_column(String(50), primary_key=True)
    window_start: Mapped[datetime] = mapped_column(primary_key=True)
    requests: Mapped[int] = mapped_column(default=0, server_default="0")
    tokens: Mapped[int] = mapped_column(default=0, server_default="0")

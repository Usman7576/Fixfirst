"""Enumerations shared by the database, API and worker (plan section 11)."""

from enum import StrEnum


class Role(StrEnum):
    ADMIN = "admin"
    DEVELOPER = "developer"
    VIEWER = "viewer"


class ScanKind(StrEnum):
    FULL = "full"
    INCREMENTAL = "incremental"


class ScanStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    WAITING_QUOTA = "waiting_quota"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


ACTIVE_SCAN_STATUSES = (ScanStatus.QUEUED, ScanStatus.RUNNING, ScanStatus.WAITING_QUOTA)


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class JobKind(StrEnum):
    SCAN = "scan"


class Tool(StrEnum):
    SEMGREP = "semgrep"
    OSV = "osv"


class Severity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class Verdict(StrEnum):
    EXPLOITABLE = "exploitable"
    NOT_EXPLOITABLE = "not_exploitable"
    UNCERTAIN = "uncertain"


class Exposure(StrEnum):
    INTERNET_FACING = "internet_facing"
    INTERNAL = "internal"
    TEST_CODE = "test_code"


class PriorityBucket(StrEnum):
    FIX_NOW = "fix_now"
    FIX_LATER = "fix_later"
    IGNORE = "ignore"


class IssueStatus(StrEnum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    FIXED = "fixed"
    FALSE_POSITIVE = "false_positive"
    ACCEPTED_RISK = "accepted_risk"


class FeedbackLabel(StrEnum):
    TRUE_POSITIVE = "true_positive"
    FALSE_POSITIVE = "false_positive"

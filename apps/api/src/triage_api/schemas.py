"""Response and request bodies. Never expose ORM-only fields such as encrypted tokens."""

import re
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_validator

from triage_core.domain import Role, ScanKind, ScanStatus

# owner/name as GitHub allows it; also keeps the value safe to put in an API path.
_FULL_NAME = re.compile(r"^[A-Za-z0-9-]{1,39}/[A-Za-z0-9._-]{1,100}$")


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class TeamMembership(BaseModel):
    team_id: uuid.UUID
    team_name: str
    role: Role


class Me(BaseModel):
    id: uuid.UUID
    login: str
    name: str | None
    email: str | None
    avatar_url: str | None
    teams: list[TeamMembership]


class AvailableRepo(BaseModel):
    github_repo_id: int
    full_name: str
    private: bool
    default_branch: str
    language: str | None
    html_url: str
    # Private repos are listed but not connectable on the free tier (plan section 16).
    connectable: bool


class ConnectRepo(BaseModel):
    team_id: uuid.UUID
    github_full_name: str

    @field_validator("github_full_name")
    @classmethod
    def _valid_full_name(cls, value: str) -> str:
        if not _FULL_NAME.match(value):
            raise ValueError("must look like owner/name")
        return value


class ScanSummary(ORM):
    id: uuid.UUID
    status: ScanStatus
    kind: ScanKind
    stage: str | None
    created_at: datetime
    finished_at: datetime | None
    raw_count: int
    issue_count: int
    fix_now_count: int


class RepoOut(ORM):
    id: uuid.UUID
    team_id: uuid.UUID
    github_full_name: str
    default_branch: str
    language: str | None
    last_scanned_at: datetime | None
    created_at: datetime
    latest_scan: ScanSummary | None = None


class ScanOut(ScanSummary):
    repo_id: uuid.UUID
    commit_sha: str | None
    progress: dict[str, object]
    started_at: datetime | None
    failure_reason: str | None
    llm_calls: int

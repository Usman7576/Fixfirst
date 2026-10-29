"""Listing, connecting and disconnecting GitHub repositories."""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import aliased

from triage_api.authz import ADMINS, ANY_ROLE, get_repo_for, require_role
from triage_api.deps import CipherDep, CurrentUser, GitHubDep, SessionDep, client_ip
from triage_api.github import GitHubError
from triage_api.schemas import AvailableRepo, ConnectRepo, RepoOut, ScanSummary
from triage_core.crypto import InvalidToken, SecretCipher
from triage_db import audit
from triage_db.models import Repository, Scan, User

router = APIRouter(prefix="/repos", tags=["repositories"])


def _github_token(cipher: SecretCipher, user: User) -> str:
    if user.gh_token_enc is None:
        raise HTTPException(409, "GitHub token missing: sign in again")
    try:
        return cipher.decrypt(user.gh_token_enc)
    except InvalidToken:
        raise HTTPException(409, "GitHub token unreadable: sign in again") from None


def _github_failure(exc: GitHubError) -> HTTPException:
    if exc.status == 401:
        return HTTPException(409, "GitHub token expired or revoked: sign in again")
    if exc.status == 404:
        return HTTPException(404, "Repository not found on GitHub")
    return HTTPException(502, "GitHub request failed")


@router.get("/available", response_model=list[AvailableRepo])
async def available_repos(
    user: CurrentUser, github: GitHubDep, cipher: CipherDep
) -> list[AvailableRepo]:
    try:
        repos = await github.list_repos(_github_token(cipher, user))
    except GitHubError as exc:
        raise _github_failure(exc) from None
    return [
        AvailableRepo(
            github_repo_id=r.id,
            full_name=r.full_name,
            private=r.private,
            default_branch=r.default_branch,
            language=r.language,
            html_url=r.html_url,
            connectable=not r.private,
        )
        for r in repos
    ]


@router.post("", response_model=RepoOut, status_code=201)
async def connect_repo(
    body: ConnectRepo,
    request: Request,
    user: CurrentUser,
    session: SessionDep,
    github: GitHubDep,
    cipher: CipherDep,
) -> RepoOut:
    await require_role(session, user, body.team_id, ADMINS)
    try:
        gh_repo = await github.get_repo(_github_token(cipher, user), body.github_full_name)
    except GitHubError as exc:
        raise _github_failure(exc) from None
    if gh_repo.private:
        raise HTTPException(422, "Private repositories are not supported on the free tier")

    repo = await session.scalar(
        select(Repository).where(
            Repository.team_id == body.team_id, Repository.github_repo_id == gh_repo.id
        )
    )
    if repo is not None and repo.deleted_at is None:
        raise HTTPException(409, "Repository is already connected")
    if repo is None:
        repo = Repository(team_id=body.team_id, github_repo_id=gh_repo.id, is_private=False)
        session.add(repo)
    repo.deleted_at = None
    repo.github_full_name = gh_repo.full_name
    repo.default_branch = gh_repo.default_branch
    repo.language = gh_repo.language
    await session.flush()
    audit.record(
        session,
        action="repo.connected",
        entity="repository",
        entity_id=repo.id,
        team_id=body.team_id,
        user_id=user.id,
        after={"github_full_name": repo.github_full_name},
        ip=client_ip(request),
    )
    await session.commit()
    return RepoOut.model_validate(repo)


@router.get("", response_model=list[RepoOut])
async def list_repos(team_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> list[RepoOut]:
    await require_role(session, user, team_id, ANY_ROLE)
    latest = (
        select(Scan.id)
        .where(Scan.repo_id == Repository.id)
        .order_by(Scan.created_at.desc())
        .limit(1)
        .correlate(Repository)
        .scalar_subquery()
    )
    latest_scan = aliased(Scan)
    rows = await session.execute(
        select(Repository, latest_scan)
        .outerjoin(latest_scan, latest_scan.id == latest)
        .where(Repository.team_id == team_id, Repository.deleted_at.is_(None))
        .order_by(Repository.github_full_name)
    )
    result = []
    for repo, scan in rows:
        out = RepoOut.model_validate(repo)
        out.latest_scan = ScanSummary.model_validate(scan) if scan else None
        result.append(out)
    return result


@router.delete("/{repo_id}", status_code=204)
async def disconnect_repo(
    repo_id: uuid.UUID, request: Request, user: CurrentUser, session: SessionDep
) -> None:
    repo = await get_repo_for(session, user, repo_id, ADMINS)
    repo.deleted_at = datetime.now(UTC)
    audit.record(
        session,
        action="repo.disconnected",
        entity="repository",
        entity_id=repo.id,
        team_id=repo.team_id,
        user_id=user.id,
        before={"github_full_name": repo.github_full_name},
        ip=client_ip(request),
    )
    await session.commit()

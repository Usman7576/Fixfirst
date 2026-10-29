"""API integration fixtures: a seeded two-team world, a fake GitHub, and auth helpers."""

import asyncio
import uuid
from collections.abc import Awaitable, Callable, Iterator
from dataclasses import dataclass, field
from typing import Any, TypeVar

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import NullPool
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from triage_api.deps import get_github
from triage_api.github import GitHubError, GitHubRepo, GitHubUser
from triage_api.main import create_app
from triage_api.security import create_access_token
from triage_core.crypto import SecretCipher
from triage_core.domain import Role, ScanStatus
from triage_core.settings import Settings
from triage_db.models import Membership, Repository, Scan, Team, User

T = TypeVar("T")
FAKE_GH_TOKEN = "gho_fake_token_for_tests"


def _repo(repo_id: int, full_name: str, *, private: bool = False) -> GitHubRepo:
    return GitHubRepo(
        id=repo_id,
        full_name=full_name,
        private=private,
        default_branch="main",
        language="Python",
        html_url=f"https://github.com/{full_name}",
    )


@dataclass
class FakeGitHub:
    user: GitHubUser = field(
        default_factory=lambda: GitHubUser(
            id=4242, login="octo", name="Octo Cat", email="octo@example.com", avatar_url=None
        )
    )
    repos: dict[str, GitHubRepo] = field(
        default_factory=lambda: {
            r.full_name: r
            for r in (
                _repo(1001, "acme/new-repo"),
                _repo(1002, "acme/secret-repo", private=True),
                _repo(1003, "acme/juice-shop"),
            )
        }
    )
    exchanged: list[tuple[str, str]] = field(default_factory=list)

    def authorize_url(self, state: str, code_challenge: str) -> str:
        return f"https://github.test/authorize?state={state}&code_challenge={code_challenge}"

    async def exchange_code(self, code: str, code_verifier: str) -> str:
        if code == "bad-code":
            raise GitHubError("code exchange failed: bad_verification_code")
        self.exchanged.append((code, code_verifier))
        return FAKE_GH_TOKEN

    async def get_user(self, token: str) -> GitHubUser:
        return self.user

    async def list_repos(self, token: str) -> list[GitHubRepo]:
        return list(self.repos.values())

    async def get_repo(self, token: str, full_name: str) -> GitHubRepo:
        if full_name not in self.repos:
            raise GitHubError("not found", status=404)
        return self.repos[full_name]


@pytest.fixture
def api_settings(clean_db: str) -> Settings:
    return Settings(  # type: ignore[call-arg]
        database_url=clean_db,
        environment="ci",
        github_client_id="test-client-id",
        github_client_secret="test-client-secret",
        _env_file=None,
    )


@pytest.fixture
def fake_github() -> FakeGitHub:
    return FakeGitHub()


@pytest.fixture
def api(api_settings: Settings, fake_github: FakeGitHub) -> Iterator[TestClient]:
    app = create_app(api_settings)
    app.dependency_overrides[get_github] = lambda: fake_github
    with TestClient(app, follow_redirects=False) as client:
        yield client


@pytest.fixture
def run_db(api_settings: Settings) -> Callable[[Callable[[AsyncSession], Awaitable[T]]], T]:
    """Runs an async function against the test DB from a synchronous test."""

    def run(fn: Callable[[AsyncSession], Awaitable[T]]) -> T:
        async def go() -> T:
            engine = create_async_engine(api_settings.database_url, poolclass=NullPool)
            try:
                async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                    return await fn(session)
            finally:
                await engine.dispose()

        return asyncio.run(go())

    return run


@dataclass
class World:
    team_a: uuid.UUID
    team_b: uuid.UUID
    repo_a: uuid.UUID
    repo_b: uuid.UUID
    scan_a: uuid.UUID
    # admin/developer/viewer are members of team A; outsider is admin of team B only.
    users: dict[str, uuid.UUID]


@pytest.fixture
def world(api_settings: Settings, run_db: Any) -> World:
    cipher = SecretCipher(api_settings.fernet_key)

    async def seed(session: AsyncSession) -> World:
        team_a, team_b = Team(name="Team A"), Team(name="Team B")
        session.add_all([team_a, team_b])
        await session.flush()
        users: dict[str, uuid.UUID] = {}
        memberships = [
            ("admin", team_a, Role.ADMIN),
            ("developer", team_a, Role.DEVELOPER),
            ("viewer", team_a, Role.VIEWER),
            ("outsider", team_b, Role.ADMIN),
        ]
        for i, (name, team, role) in enumerate(memberships):
            user = User(github_id=9000 + i, login=name, gh_token_enc=cipher.encrypt(FAKE_GH_TOKEN))
            session.add(user)
            await session.flush()
            session.add(Membership(team_id=team.id, user_id=user.id, role=role))
            users[name] = user.id
        repo_a = Repository(
            team_id=team_a.id,
            github_repo_id=1,
            github_full_name="acme/app-a",
            default_branch="main",
            is_private=False,
        )
        repo_b = Repository(
            team_id=team_b.id,
            github_repo_id=2,
            github_full_name="acme/app-b",
            default_branch="main",
            is_private=False,
        )
        session.add_all([repo_a, repo_b])
        await session.flush()
        scan_a = Scan(repo_id=repo_a.id, status=ScanStatus.DONE)
        session.add(scan_a)
        await session.commit()
        return World(team_a.id, team_b.id, repo_a.id, repo_b.id, scan_a.id, users)

    result: World = run_db(seed)
    return result


@pytest.fixture
def auth(api_settings: Settings) -> Callable[[uuid.UUID], dict[str, str]]:
    def headers(user_id: uuid.UUID) -> dict[str, str]:
        return {"Authorization": f"Bearer {create_access_token(api_settings, user_id)}"}

    return headers

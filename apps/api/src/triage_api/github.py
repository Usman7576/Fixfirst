"""Minimal GitHub client for OAuth and repository metadata. Tokens are never logged."""

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import httpx

from triage_core.settings import Settings

OAUTH_SCOPES = "read:user user:email"
API = "https://api.github.com"
MAX_REPO_PAGES = 5


class GitHubError(Exception):
    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class GitHubUser:
    id: int
    login: str
    name: str | None
    email: str | None
    avatar_url: str | None


@dataclass(frozen=True)
class GitHubRepo:
    id: int
    full_name: str
    private: bool
    default_branch: str
    language: str | None
    html_url: str

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> "GitHubRepo":
        return cls(
            id=data["id"],
            full_name=data["full_name"],
            private=data["private"],
            default_branch=data["default_branch"],
            language=data.get("language"),
            html_url=data["html_url"],
        )


class GitHubClient:
    def __init__(self, settings: Settings, http: httpx.AsyncClient) -> None:
        self._settings = settings
        self._http = http

    def authorize_url(self, state: str, code_challenge: str) -> str:
        query = urlencode(
            {
                "client_id": self._settings.github_client_id,
                "redirect_uri": self._settings.oauth_redirect_url,
                "scope": OAUTH_SCOPES,
                "state": state,
                "code_challenge": code_challenge,
                "code_challenge_method": "S256",
                "allow_signup": "false",
            }
        )
        return f"https://github.com/login/oauth/authorize?{query}"

    async def exchange_code(self, code: str, code_verifier: str) -> str:
        secret = self._settings.github_client_secret
        response = await self._http.post(
            "https://github.com/login/oauth/access_token",
            data={
                "client_id": self._settings.github_client_id,
                "client_secret": secret.get_secret_value() if secret else "",
                "code": code,
                "redirect_uri": self._settings.oauth_redirect_url,
                "code_verifier": code_verifier,
            },
            headers={"Accept": "application/json"},
        )
        body = response.json() if response.is_success else {}
        token = body.get("access_token")
        if not token:
            # GitHub returns 200 with an "error" field for bad or expired codes.
            raise GitHubError(f"code exchange failed: {body.get('error', response.status_code)}")
        return str(token)

    async def get_user(self, token: str) -> GitHubUser:
        data = await self._get(token, "/user")
        email = data.get("email") or await self._primary_email(token)
        return GitHubUser(
            id=data["id"],
            login=data["login"],
            name=data.get("name"),
            email=email,
            avatar_url=data.get("avatar_url"),
        )

    async def list_repos(self, token: str) -> list[GitHubRepo]:
        repos: list[GitHubRepo] = []
        for page in range(1, MAX_REPO_PAGES + 1):
            batch = await self._get(
                token, "/user/repos", params={"per_page": 100, "page": page, "sort": "updated"}
            )
            repos.extend(GitHubRepo.from_api(item) for item in batch)
            if len(batch) < 100:
                break
        return repos

    async def get_repo(self, token: str, full_name: str) -> GitHubRepo:
        return GitHubRepo.from_api(await self._get(token, f"/repos/{full_name}"))

    async def _primary_email(self, token: str) -> str | None:
        try:
            emails = await self._get(token, "/user/emails")
        except GitHubError:
            return None
        for item in emails:
            if item.get("primary") and item.get("verified"):
                return str(item["email"])
        return None

    async def _get(self, token: str, path: str, params: dict[str, Any] | None = None) -> Any:
        response = await self._http.get(
            f"{API}{path}",
            params=params,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        if not response.is_success:
            raise GitHubError(f"GET {path} failed", status=response.status_code)
        return response.json()

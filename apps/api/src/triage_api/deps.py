"""FastAPI dependencies: settings, DB sessions, GitHub client, the current user."""

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from triage_api.github import GitHubClient
from triage_api.security import InvalidTokenError, decode_access_token
from triage_core.crypto import SecretCipher
from triage_core.settings import Settings
from triage_db.models import User


def get_app_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    async with request.app.state.session_factory() as session:
        yield session


def get_github(request: Request) -> GitHubClient:
    client: GitHubClient = request.app.state.github
    return client


def get_cipher(request: Request) -> SecretCipher:
    cipher: SecretCipher = request.app.state.cipher
    return cipher


SettingsDep = Annotated[Settings, Depends(get_app_settings)]
SessionDep = Annotated[AsyncSession, Depends(get_session)]
GitHubDep = Annotated[GitHubClient, Depends(get_github)]
CipherDep = Annotated[SecretCipher, Depends(get_cipher)]

_bearer = HTTPBearer(auto_error=False)
_UNAUTHENTICATED = HTTPException(401, "Not authenticated", headers={"WWW-Authenticate": "Bearer"})


async def get_current_user(
    settings: SettingsDep,
    session: SessionDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> User:
    if credentials is None:
        raise _UNAUTHENTICATED
    try:
        user_id = decode_access_token(settings, credentials.credentials)
    except InvalidTokenError:
        raise _UNAUTHENTICATED from None
    user = await session.get(User, user_id)
    if user is None:
        raise _UNAUTHENTICATED
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None

"""Token primitives: access JWTs, opaque refresh tokens, and the OAuth state cookie."""

import base64
import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt

from triage_core.settings import Settings

ISSUER = "fixfirst"
ALGORITHM = "HS256"


class InvalidTokenError(Exception):
    pass


def create_access_token(settings: Settings, user_id: uuid.UUID) -> str:
    now = datetime.now(UTC)
    claims = {
        "sub": str(user_id),
        "iss": ISSUER,
        "iat": now,
        "exp": now + timedelta(seconds=settings.access_token_ttl_s),
        "typ": "access",
    }
    return jwt.encode(
        claims, settings.jwt_key, algorithm=ALGORITHM, headers={"kid": settings.jwt_key_id}
    )


def decode_access_token(settings: Settings, token: str) -> uuid.UUID:
    try:
        claims = jwt.decode(
            token,
            settings.jwt_key,
            algorithms=[ALGORITHM],
            issuer=ISSUER,
            options={"require": ["exp", "iat", "sub", "iss"]},
        )
        if claims.get("typ") != "access":
            raise InvalidTokenError("not an access token")
        return uuid.UUID(claims["sub"])
    except (jwt.PyJWTError, ValueError) as exc:
        raise InvalidTokenError(str(exc)) from exc


def new_refresh_token() -> tuple[str, str]:
    """Returns (token for the cookie, hash for the database)."""
    token = secrets.token_urlsafe(32)
    return token, hash_refresh_token(token)


def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@dataclass(frozen=True)
class OAuthState:
    state: str
    code_verifier: str

    @property
    def code_challenge(self) -> str:
        digest = hashlib.sha256(self.code_verifier.encode()).digest()
        return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


OAUTH_STATE_TTL_S = 600


def new_oauth_state() -> OAuthState:
    return OAuthState(state=secrets.token_urlsafe(32), code_verifier=secrets.token_urlsafe(64))


def encode_oauth_state(settings: Settings, oauth: OAuthState) -> str:
    """Signed, short-lived cookie value so the callback needs no server-side session."""
    now = datetime.now(UTC)
    claims = {
        "state": oauth.state,
        "cv": oauth.code_verifier,
        "iss": ISSUER,
        "exp": now + timedelta(seconds=OAUTH_STATE_TTL_S),
        "typ": "oauth_state",
    }
    return jwt.encode(claims, settings.jwt_key, algorithm=ALGORITHM)


def decode_oauth_state(settings: Settings, value: str) -> OAuthState:
    try:
        claims = jwt.decode(value, settings.jwt_key, algorithms=[ALGORITHM], issuer=ISSUER)
    except jwt.PyJWTError as exc:
        raise InvalidTokenError(str(exc)) from exc
    if claims.get("typ") != "oauth_state":
        raise InvalidTokenError("not an oauth state token")
    return OAuthState(state=claims["state"], code_verifier=claims["cv"])

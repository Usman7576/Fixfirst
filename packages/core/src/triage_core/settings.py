"""Runtime configuration, read from the environment and validated once at startup."""

import base64
import hashlib
import tempfile
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Literal, Self

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR"]

# Fixed keys so local dev and CI work without setup. Rejected outside local/ci (see validator).
_DEV_JWT_KEY = "fixfirst-local-development-jwt-key-not-secret"
_DEV_FERNET_KEY = base64.urlsafe_b64encode(hashlib.sha256(b"fixfirst-local-dev-only").digest())


class Environment(StrEnum):
    LOCAL = "local"
    CI = "ci"
    STAGING = "staging"
    PRODUCTION = "production"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    environment: Environment = Environment.LOCAL
    log_level: LogLevel = "INFO"

    # No default: a missing database URL must fail fast rather than silently use localhost.
    database_url: str
    db_pool_size: int = Field(default=5, ge=1, le=50)

    web_origin: str = "http://localhost:5173"
    # Public base URL of this API; the GitHub OAuth callback is registered under it.
    api_public_url: str = "http://localhost:8000"

    github_client_id: str | None = None
    github_client_secret: SecretStr | None = None

    jwt_signing_key: SecretStr | None = Field(default=None, min_length=32)
    jwt_key_id: str = "v1"
    access_token_ttl_s: int = Field(default=15 * 60, ge=60)
    refresh_token_ttl_s: int = Field(default=7 * 24 * 3600, ge=3600)
    # Fernet key for GitHub tokens and webhook URLs at rest.
    token_encryption_key: SecretStr | None = None

    worker_poll_interval_s: float = Field(default=1.0, gt=0, le=60)
    worker_heartbeat_file: Path = Path(tempfile.gettempdir()) / "triage-worker-heartbeat"
    job_lease_s: int = Field(default=60, ge=10)
    job_max_attempts: int = Field(default=3, ge=1)

    # Scanning limits (plan section 8.1). Clones live under scan_work_dir only while scanning.
    scan_work_dir: Path = Path(tempfile.gettempdir()) / "fixfirst-scans"
    scan_max_repo_mb: int = Field(default=200, ge=1)
    scan_max_files: int = Field(default=20_000, ge=1)
    scan_clone_timeout_s: int = Field(default=120, ge=5)
    scan_timeout_s: int = Field(default=600, ge=10)
    semgrep_bin: str = "semgrep"
    semgrep_rules_dir: Path = Path("/opt/semgrep-rules")
    osv_scanner_bin: str = "osv-scanner"

    @field_validator("database_url")
    @classmethod
    def _require_async_driver(cls, value: str) -> str:
        if not value.startswith("postgresql+asyncpg://"):
            raise ValueError("DATABASE_URL must use the postgresql+asyncpg:// driver")
        return value

    @model_validator(mode="after")
    def _require_real_secrets_when_deployed(self) -> Self:
        if self.environment in (Environment.LOCAL, Environment.CI):
            return self
        required = ("jwt_signing_key", "token_encryption_key", "github_client_id")
        missing = [name.upper() for name in required if getattr(self, name) is None]
        if self.github_client_secret is None:
            missing.append("GITHUB_CLIENT_SECRET")
        if missing:
            raise ValueError(f"{', '.join(missing)} must be set in {self.environment}")
        return self

    @property
    def is_production(self) -> bool:
        return self.environment is Environment.PRODUCTION

    @property
    def json_logs(self) -> bool:
        return self.environment is not Environment.LOCAL

    @property
    def secure_cookies(self) -> bool:
        return self.environment in (Environment.STAGING, Environment.PRODUCTION)

    @property
    def github_oauth_configured(self) -> bool:
        secret = self.github_client_secret.get_secret_value() if self.github_client_secret else ""
        return bool(self.github_client_id and secret)

    @property
    def oauth_redirect_url(self) -> str:
        return f"{self.api_public_url.rstrip('/')}/api/v1/auth/github/callback"

    @property
    def jwt_key(self) -> str:
        return self.jwt_signing_key.get_secret_value() if self.jwt_signing_key else _DEV_JWT_KEY

    @property
    def fernet_key(self) -> bytes:
        if self.token_encryption_key:
            return self.token_encryption_key.get_secret_value().encode()
        return _DEV_FERNET_KEY


@lru_cache
def get_settings() -> Settings:
    return Settings()  # values come from the environment

"""Runtime configuration, read from the environment and validated once at startup."""

import tempfile
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR"]


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

    worker_poll_interval_s: float = Field(default=1.0, gt=0, le=60)
    worker_heartbeat_file: Path = Path(tempfile.gettempdir()) / "triage-worker-heartbeat"

    @field_validator("database_url")
    @classmethod
    def _require_async_driver(cls, value: str) -> str:
        if not value.startswith("postgresql+asyncpg://"):
            raise ValueError("DATABASE_URL must use the postgresql+asyncpg:// driver")
        return value

    @property
    def is_production(self) -> bool:
        return self.environment is Environment.PRODUCTION

    @property
    def json_logs(self) -> bool:
        return self.environment is not Environment.LOCAL


@lru_cache
def get_settings() -> Settings:
    return Settings()  # values come from the environment

"""Application factory."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from triage_api.errors import register_error_handlers
from triage_api.github import GitHubClient
from triage_api.middleware import REQUEST_ID_HEADER, register_middleware
from triage_api.routes import auth, health, me, repos, scans
from triage_core.crypto import SecretCipher
from triage_core.logging import configure_logging
from triage_core.settings import Settings, get_settings
from triage_db.engine import create_engine, create_session_factory

API_PREFIX = "/api/v1"


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, json=settings.json_logs)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.engine = create_engine(settings)
        app.state.session_factory = create_session_factory(app.state.engine)
        http = httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=5.0))
        app.state.github = GitHubClient(settings, http)
        app.state.cipher = SecretCipher(settings.fernet_key)
        try:
            yield
        finally:
            await http.aclose()
            await app.state.engine.dispose()

    # Interactive docs are useful locally but are an unnecessary surface in production.
    docs_enabled = not settings.is_production
    app = FastAPI(
        title="Fixfirst API",
        version="0.1.0",
        lifespan=lifespan,
        openapi_url=f"{API_PREFIX}/openapi.json" if docs_enabled else None,
        docs_url=f"{API_PREFIX}/docs" if docs_enabled else None,
        redoc_url=None,
    )
    app.state.settings = settings

    register_error_handlers(app)
    register_middleware(app)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.web_origin],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
        allow_headers=["Authorization", "Content-Type", REQUEST_ID_HEADER, "Idempotency-Key"],
        expose_headers=[REQUEST_ID_HEADER],
    )

    for router in (health.router, auth.router, me.router, repos.router, scans.router):
        app.include_router(router, prefix=API_PREFIX)
    return app

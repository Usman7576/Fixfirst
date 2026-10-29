"""Application factory."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from triage_api.errors import register_error_handlers
from triage_api.middleware import REQUEST_ID_HEADER, register_middleware
from triage_api.routes import health
from triage_core.logging import configure_logging
from triage_core.settings import Settings, get_settings
from triage_db.engine import create_engine

API_PREFIX = "/api/v1"


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, json=settings.json_logs)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.engine = create_engine(settings)
        try:
            yield
        finally:
            await app.state.engine.dispose()

    # Interactive docs are useful locally but are an unnecessary surface in production.
    docs_enabled = not settings.is_production
    app = FastAPI(
        title="AI Security Triage API",
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

    app.include_router(health.router, prefix=API_PREFIX)
    return app

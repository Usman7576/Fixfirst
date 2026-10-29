# syntax=docker/dockerfile:1.7
# One image for the API, the worker and the migration job; the command picks the role.
# Build from the repo root: docker build -f infra/docker/backend.Dockerfile .

FROM python:3.12-slim-bookworm AS build
COPY --from=ghcr.io/astral-sh/uv:0.13.5 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv
WORKDIR /src

# Third-party dependencies first, so code changes don't invalidate this layer.
COPY pyproject.toml uv.lock ./
COPY apps/api/pyproject.toml apps/api/
COPY apps/worker/pyproject.toml apps/worker/
COPY packages/core/pyproject.toml packages/core/
COPY packages/db/pyproject.toml packages/db/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-workspace

COPY apps/api apps/api
COPY apps/worker apps/worker
COPY packages/core packages/core
COPY packages/db packages/db
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable

FROM python:3.12-slim-bookworm AS runtime
RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin app
COPY --from=build /opt/venv /opt/venv
COPY packages/db/alembic.ini /app/alembic.ini
ENV PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
USER app
EXPOSE 8000
CMD ["uvicorn", "triage_api.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--no-access-log"]

# syntax=docker/dockerfile:1.7
# Two targets from one build:
#   api     - FastAPI service (also runs migrations)
#   worker  - adds git, Semgrep, OSV-Scanner and the pinned Semgrep rules
# Build from the repo root:  docker build -f infra/docker/backend.Dockerfile --target worker .

ARG PYTHON_IMAGE=python:3.12-slim-bookworm
ARG SEMGREP_VERSION=1.182.1
ARG OSV_SCANNER_VERSION=2.7.0
# semgrep/semgrep-rules commit (2026-10-21). Check the rules licence before commercial use.
ARG SEMGREP_RULES_COMMIT=16b9e6d45f10649f6a531ec4838ed9924372c3bc

# ---------------------------------------------------------------- app dependencies
FROM ${PYTHON_IMAGE} AS build
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

# ---------------------------------------------------------------- semgrep rules
FROM alpine:3.20 AS rules
ARG SEMGREP_RULES_COMMIT
ADD https://github.com/semgrep/semgrep-rules/archive/${SEMGREP_RULES_COMMIT}.tar.gz /tmp/rules.tgz
RUN mkdir -p /out \
 && tar -xzf /tmp/rules.tgz -C /tmp \
 && for lang in python javascript typescript; do \
      cp -r "/tmp/semgrep-rules-${SEMGREP_RULES_COMMIT}/${lang}" /out/; \
    done \
 # Keep rule files only; the repo stores test targets next to each rule.
 && find /out -type f ! -name '*.yaml' ! -name '*.yml' -delete \
 && find /out -type f \( -name '*.test.yaml' -o -name '*.test.yml' \) -delete \
 && find /out -type d -empty -delete

# ---------------------------------------------------------------- shared runtime
FROM ${PYTHON_IMAGE} AS runtime
RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin app
COPY --from=build /opt/venv /opt/venv
COPY packages/db/alembic.ini /app/alembic.ini
ENV PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
WORKDIR /app

# ---------------------------------------------------------------- api
FROM runtime AS api
USER app
EXPOSE 8000
CMD ["uvicorn", "triage_api.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--no-access-log"]

# ---------------------------------------------------------------- worker
FROM runtime AS worker
ARG SEMGREP_VERSION
ARG OSV_SCANNER_VERSION
ARG TARGETARCH
RUN apt-get update \
 && apt-get install -y --no-install-recommends git ca-certificates \
 && rm -rf /var/lib/apt/lists/*
# Semgrep in its own venv so its pins never conflict with the app's.
RUN python -m venv /opt/semgrep \
 && /opt/semgrep/bin/pip install --no-cache-dir "semgrep==${SEMGREP_VERSION}" \
 && ln -s /opt/semgrep/bin/semgrep /usr/local/bin/semgrep
# Checksums from the release's osv-scanner_SHA256SUMS.
ADD --chmod=755 --checksum=sha256:160c6253e2922e9e0a6a9771c5c4c40a4b3c6090b34a3cdd5e80c96cc2e4218b \
    https://github.com/google/osv-scanner/releases/download/v${OSV_SCANNER_VERSION}/osv-scanner_linux_amd64 /opt/osv/osv-scanner-amd64
ADD --chmod=755 --checksum=sha256:4061ef4c021ed3c47f203b818f337e351336cc5cd67c0274fc36bd1dfc728dd7 \
    https://github.com/google/osv-scanner/releases/download/v${OSV_SCANNER_VERSION}/osv-scanner_linux_arm64 /opt/osv/osv-scanner-arm64
RUN ln -s "/opt/osv/osv-scanner-${TARGETARCH:-amd64}" /usr/local/bin/osv-scanner
COPY --from=rules /out /opt/semgrep-rules
USER app
# Fail the build, not the first scan, if a tool is missing or broken.
RUN semgrep --version && osv-scanner --version && git --version
CMD ["python", "-m", "triage_worker"]

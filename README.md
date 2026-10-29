# AI Security Triage Platform

> "Your scanner found 847 issues. We tell you which 12 are real, which 3 to fix today, and how."

Connects to a GitHub repository, runs Semgrep and OSV-Scanner, deduplicates the findings, and uses an
LLM pipeline to judge exploitability, rank and explain each issue, and suggest fixes.

**Status:** week 1 — foundation. See the [planning document](docs/AI-Security-Triage-Platform-Plan.pdf)
for the full design and roadmap, and [docs/adr](docs/adr/README.md) for the decisions behind it.

## Repository layout

```
apps/
  api/        FastAPI service (auth, repos, scans, issues). Never calls an LLM.
  worker/     Background worker: claims jobs, runs scanners and the triage pipeline.
  web/        React + Vite SPA.
packages/
  core/       Settings, logging, domain logic shared by api and worker.
  db/         SQLAlchemy models, engine helpers, Alembic migrations.
infra/        Dockerfiles and database init scripts.
docs/         Planning document, ADRs, provider limits.
```

## Run everything with Docker

Needs Docker Desktop (Windows: WSL2 backend).

```bash
docker compose up --build
```

| Service | URL |
| --- | --- |
| Web | http://localhost:5173 |
| API docs | http://localhost:8000/api/v1/docs |
| Liveness / readiness | http://localhost:8000/api/v1/health · `/ready` |
| Postgres | `localhost:5432`, user/password/db `triage` (set `DB_PORT` if 5432 is taken) |

The `migrate` service applies Alembic migrations before the API and worker start. The API is
healthy only when the database is reachable and migrated to head; the worker is healthy while its
heartbeat file is fresh.

## Develop without Docker

Needs [uv](https://docs.astral.sh/uv/) and Node 22+. Postgres can still come from Compose:
`docker compose up -d db`.

```bash
uv sync
```

```bash
cp .env.example .env
```

```bash
uv run alembic -c packages/db/alembic.ini upgrade head
```

```bash
uv run uvicorn triage_api.main:create_app --factory --reload
```

```bash
uv run python -m triage_worker
```

```bash
cd apps/web && npm install && npm run dev
```

## Quality checks

The same checks run in CI (`.github/workflows/ci.yml`).

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest
```

```bash
cd apps/web && npm run lint && npm run format:check && npm run typecheck && npm test
```

Integration tests (marked `integration`) run when `TEST_DATABASE_URL` is set; Compose creates a
`triage_test` database for them. Install the git hooks once with `uv run pre-commit install`.

## Privacy

Only public repositories are supported on the free tier: code snippets are sent to third-party LLM
providers whose free plans may use submitted data.

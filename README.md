# Fixfirst

**AI security triage for small teams.**

> "Your scanner found 847 issues. We tell you which 12 are real, which 3 to fix today, and how."

Connects to a GitHub repository, runs Semgrep and OSV-Scanner, deduplicates the findings, and uses an
LLM pipeline to judge exploitability, rank and explain each issue, and suggest fixes.

**Status:** week 2 — data model, GitHub sign-in, repositories and the job queue. Scans are queued
and picked up by the worker, but the scanning pipeline itself arrives in week 3. See the
[planning document](docs/Fixfirst-Planning-Document.pdf)
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

### GitHub sign-in

Sign-in needs your own GitHub OAuth App (without one, `/auth/github/login` returns 503):

1. GitHub → **Settings → Developer settings → OAuth Apps → New OAuth App**.
2. Homepage URL `http://localhost:5173`; callback URL
   `http://localhost:8000/api/v1/auth/github/callback`.
3. Put the client ID and a generated client secret in a `.env` file at the repo root
   (it is git-ignored; Compose reads it automatically):

```bash
printf 'GITHUB_CLIENT_ID=%s\nGITHUB_CLIENT_SECRET=%s\n' "<client id>" "<client secret>" >> .env
```

The app asks only for `read:user user:email`, so it can list your public repositories but
cannot change anything on GitHub.

Local and CI runs use fixed development keys for JWT signing and token encryption. Staging and
production refuse to start unless `JWT_SIGNING_KEY` (32+ characters), `TOKEN_ENCRYPTION_KEY`
(a Fernet key) and the GitHub credentials are set.

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

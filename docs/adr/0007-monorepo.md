# 0007 — Monorepo with a uv workspace

**Status:** Accepted · 2026-10-29

## Context
The API, worker, shared domain code and web app change together, especially schemas.

## Decision
One repository. Python code is a uv workspace (`apps/api`, `apps/worker`, `packages/core`,
`packages/db`, later `packages/pipeline`) with a single lockfile; the web app lives in `apps/web`
with its own npm lockfile. One CI workflow gates everything.

## Consequences
- Atomic changes across API, worker and schemas; one version of every dependency.
- CI runs more than a change strictly needs (acceptable at this size; path filters can come later).

## Revisit when
The team grows past ~8 engineers or CI time becomes a bottleneck.

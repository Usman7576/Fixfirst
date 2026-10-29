# 0002 — Separate worker process

**Status:** Accepted · 2026-10-29

## Context
Scanning clones untrusted repositories, runs CPU-heavy scanners and waits on rate-limited LLM
providers. None of that belongs on the request path.

## Decision
The API and the worker are separate processes built from the same image. The API only enqueues
work and reads results; **only the worker calls LLMs**, through one router that enforces limits.
The worker runs as a non-root user with no secrets beyond what scanning and triage need.

## Consequences
- API latency is independent of scan load and provider rate limits.
- Untrusted-code handling is isolated in one place that can be sandboxed further.
- Two deployables instead of one; some free hosts don't offer free background workers
  (see `docs/providers.md`).

## Revisit when
Never for the API/worker split itself; the hosting arrangement may change.

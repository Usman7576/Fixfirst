# 0001 — Postgres jobs table instead of Redis/Celery

**Status:** Accepted · 2026-10-29

## Context
Scans run for minutes and must survive worker crashes and deploys. The free hosting budget leaves
no room for a separate Redis instance, and every extra service is one more thing to secure.

## Decision
Background work lives in a `jobs` table. Workers claim a job with
`SELECT … FOR UPDATE SKIP LOCKED`, hold a time-limited lease that a heartbeat extends, and a reaper
re-queues jobs whose lease expired. Enqueueing happens in the same transaction that creates the
`scans` row, so a scan can never exist without its job (or vice versa).

## Consequences
- One datastore to back up and monitor; transactional enqueue for free.
- Polling adds a little load (one indexed query per idle second per worker).
- Throughput ceiling is far above MVP needs but lower than a dedicated broker.

## Revisit when
Sustained load exceeds ~50 jobs/minute, or we need scheduled fan-out / priorities that the table
design makes awkward.

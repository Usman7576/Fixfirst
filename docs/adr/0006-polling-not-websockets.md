# 0006 — Polling instead of WebSockets for scan progress

**Status:** Accepted · 2026-10-29

## Context
The dashboard shows scan progress that changes every few seconds for a few minutes.

## Decision
The SPA polls `GET /scans/{id}` with TanStack Query: every 2 s while a scan is running, backing off
when idle.

## Consequences
- Works on any free host and through any proxy; responses are cacheable and stateless.
- Slightly more requests than push; negligible at MVP scale.

## Revisit when
Many concurrent viewers make polling load noticeable, or we need sub-second updates.

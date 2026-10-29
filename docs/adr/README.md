# Architecture Decision Records

Short records of significant decisions: context, the decision, and what would make us revisit it.
Add a new file `NNNN-title.md` for each decision; never rewrite an accepted one — supersede it.

| ADR | Decision | Status |
| --- | --- | --- |
| [0001](0001-postgres-job-queue.md) | Postgres jobs table instead of Redis/Celery | Accepted |
| [0002](0002-separate-worker-process.md) | Separate worker process for scans and LLM calls | Accepted |
| [0003](0003-litellm-role-model-config.md) | LiteLLM behind a role → model config | Accepted |
| [0004](0004-langgraph-triage.md) | LangGraph for the triage pipeline | Accepted |
| [0005](0005-fingerprint-excludes-lines.md) | Fingerprints exclude line numbers | Accepted |
| [0006](0006-polling-not-websockets.md) | Polling instead of WebSockets for scan progress | Accepted |
| [0007](0007-monorepo.md) | Monorepo with a uv workspace | Accepted |

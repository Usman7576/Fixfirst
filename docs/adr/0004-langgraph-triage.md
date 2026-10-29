# 0004 — LangGraph for the triage pipeline

**Status:** Accepted · 2026-10-29

## Context
Triage is a sequence of steps with a conditional branch (quick verdict → deep analysis only when
uncertain or critical) and must resume after a crash without repeating LLM calls.

## Decision
Model the pipeline as a LangGraph graph over a typed `TriageState`, one node per step, with a
checkpoint after each node.

## Consequences
- Routing logic is explicit and unit-testable per node.
- Checkpoints give resumability for free.
- Adds a framework dependency and some overhead for what is mostly a linear flow.

## Revisit when
Graph features go unused and the overhead shows up in tests or debugging.

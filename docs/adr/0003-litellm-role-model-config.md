# 0003 — LiteLLM behind a role → model config

**Status:** Accepted · 2026-10-29

## Context
We start on Groq and Gemini free tiers, whose models, limits and terms change often, and expect to
move to paid models later.

## Decision
Pipeline nodes call a single `llm(role, messages, schema)` function. `config/models.yaml` maps each
role (`quick_triage`, `deep_analysis`, `explain_fix`) to an ordered chain of models. LiteLLM handles
the provider APIs; our router adds token buckets, backoff, circuit breakers and fallback.

## Consequences
- Swapping a model is a config change, and the evaluation set measures the impact.
- We depend on LiteLLM keeping pace with provider features.

## Revisit when
LiteLLM blocks a provider feature we need (e.g. a structured-output mode) for more than a release.

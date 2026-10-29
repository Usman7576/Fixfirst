# Provider limits and terms

Free-tier limits and terms change often. Fill this in from each provider's **current** pricing,
limits and terms pages during week 1, and re-check before launch. Router token buckets are set to
~80% of the numbers recorded here (plan §9.5).

Last verified: _not yet_ — by: _\<name\>_

## LLM providers

| Provider | Model ID (role) | RPM | TPM | Requests/day | Context window | Free tier uses data for training? | Source URL |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Groq | _tbd_ (quick_triage) | | | | | | |
| Groq | _tbd_ (deep_analysis fallback) | | | | | | |
| Google Gemini | _tbd Flash_ (deep_analysis, explain_fix) | | | | | | |

## Hosting and data

| Service | Plan | Limits that matter | Sleeps when idle? | Commercial use allowed? | Source URL |
| --- | --- | --- | --- | --- | --- |
| Vercel (web) | Hobby | | n/a | | |
| Render / Railway / Fly.io (api) | | | | | |
| Render / Railway / Fly.io (worker) | | background workers on free plan? | | | |
| Neon / Supabase (Postgres) | | storage, compute hours, backups/PITR | | | |
| Sentry | Free | events/month | n/a | | |

## Scanners and rule licensing

| Item | Version pinned | Licence | Restrictions for a hosted product | Source URL |
| --- | --- | --- | --- | --- |
| Semgrep CE engine | 1.182.1 (PyPI) | LGPL-2.1 | | https://pypi.org/project/semgrep/ |
| Semgrep rules: `python/`, `javascript/`, `typescript/` from semgrep/semgrep-rules | commit `16b9e6d` (2026-10-21) | Semgrep Rules License (GitHub reports "Other") | Check before selling: it restricts offering the rules in a competing hosted product | https://github.com/semgrep/semgrep-rules |
| OSV-Scanner | v2.7.0, SHA-256 verified at image build | Apache-2.0 | | https://github.com/google/osv-scanner/releases/tag/v2.7.0 |
| OSV database | queried online at scan time (api.osv.dev) | | Consider offline DB mode to remove the runtime dependency | https://osv.dev |

Versions are pinned in `infra/docker/backend.Dockerfile` (build args). Bump them there.

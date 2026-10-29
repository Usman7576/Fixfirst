# 0005 — Fingerprints exclude line numbers

**Status:** Accepted · 2026-10-29

## Context
An issue must keep its identity across scans so its status, assignee and feedback survive, and so a
missing fingerprint can mean "fixed".

## Decision
`fingerprint = sha256(rule_id | file_path | normalised_snippet | occurrence_index)`, where the
snippet is normalised (comments stripped, whitespace collapsed, identifiers replaced with positional
placeholders). Line numbers are excluded; `occurrence_index` separates identical snippets in one
file. A `fingerprint_version` column allows the algorithm to evolve with a re-mapping migration.

## Consequences
- Edits above the code don't create new issues.
- Moving code to another file does create a new issue (acceptable).
- Normalisation must be covered by property tests to stay stable.

## Revisit when
The evaluation set or issue churn metrics show collisions or unstable fingerprints.

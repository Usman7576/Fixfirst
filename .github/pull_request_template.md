## What and why

<!-- Requirement ID(s) from the plan, e.g. FR-03 -->
Implements:

## Checklist

- [ ] Tests at the right level (unit / integration / authz / e2e)
- [ ] Migrations are reversible (expand/contract if the change touches live data)
- [ ] New failure modes are logged with request_id / scan_id
- [ ] Touches auth, jobs, cloning or prompts → security checklist reviewed (plan §15)
- [ ] Docs, ADR or runbook updated if behaviour changed

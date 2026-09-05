# Codex Phase Review Template

Audit the completed phase against:
- AGENTS.md
- MASTER_PROMPT.md
- ROADMAP.md
- architecture docs
- ADRs

Do not modify files initially.

Inspect the actual implementation, not only documentation.

Run the appropriate:
- backend tests
- frontend tests
- lint
- typecheck
- production build
- migration checks

Review:
- authentication
- session security
- organization isolation
- RBAC
- API authorization
- database constraints
- migration correctness
- error handling
- frontend/backend boundaries
- secret handling
- test coverage
- race conditions
- edge cases
- performance regressions
- security regressions

Look for cases where tests pass but the business/security invariant is not actually protected.

Classify findings:
- P0
- P1
- P2
- P3

For each finding include:
- problem
- impact
- evidence
- affected files
- recommended fix

End with:

APPROVE

or

BLOCK

If BLOCK, list the exact P0/P1 items required before proceeding.

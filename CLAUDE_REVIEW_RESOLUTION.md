# Claude Prompt — Resolve Codex Review Findings

Read:
- AGENTS.md
- CLAUDE.md
- the latest Codex review
- relevant architecture docs
- ROADMAP.md

Review every Codex finding critically.

Do not automatically accept every recommendation.

For each P0/P1 finding:

1. Determine whether it is valid.
2. Explain the reasoning.
3. Implement the correction if valid.
4. If rejected, explain why with evidence.
5. Add or update regression tests.
6. Update relevant architecture docs/ADRs.
7. Update ROADMAP.md.
8. Run the full relevant verification suite.

Do not start the next phase.

At the end provide a resolution table:

| Finding | Accepted/Rejected | Reason | Files Changed | Test/Verification | Resolution |
|---|---|---|---|---|---|

Stop after all current P0/P1 findings have been addressed.

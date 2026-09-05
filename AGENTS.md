# Trinol OS — Shared Agent Operating Guide

This file is the single source of truth for all coding agents working on Trinol OS.

## Product
Trinol OS is TrinolIT's internal company operating system, designed to later evolve into a SaaS product for software agencies, startups, and SMEs.

Company: TrinolIT  
Website: https://www.trinolit.com  
Primary email: hello@trinolit.com

## Core Principle
Build a product TrinolIT can genuinely use every day.

Do not optimize for generating lots of code. Optimize for:
- correctness
- maintainability
- security
- excellent UX
- testability
- production readiness

## Agent Roles
Primary builder: Claude Code  
Independent reviewer / verifier / targeted fixer: Codex

Do not have two agents implement the same feature in parallel unless using isolated branches/worktrees and the task is explicitly coordinated.

## Required Workflow
For every phase:

1. Read this file and all relevant architecture/product documents.
2. Inspect existing code before making changes.
3. Plan before implementation.
4. Implement only the requested scope.
5. Run lint, typecheck, tests, and build.
6. Commit with a clear message.
7. Send the phase to an independent audit.
8. Resolve P0/P1 findings before starting the next phase.
9. Update ROADMAP.md and CHANGELOG.md.

## Severity
P0 — Critical. Must block release/phase progression.  
P1 — Important. Must be fixed before proceeding.  
P2 — Improvement. Can proceed with tracking.  
P3 — Optional.

## Development Rules
- Never fabricate passing tests.
- Never suppress failing tests to make CI green.
- Never commit secrets.
- Never expose credentials to browser code.
- Backend owns business rules.
- Frontend hiding is not authorization.
- Database constraints should enforce invariants where appropriate.
- Avoid giant components and giant service classes.
- Avoid unnecessary abstractions.
- Avoid introducing libraries without justification.
- Fix root causes.
- Do not silently change product requirements.
- Record important architectural decisions in ADRs.
- Keep ROADMAP.md current.

## Definition of Done
A feature is not done just because a page exists.

A feature is complete only when:
- UI exists
- backend exists
- validation exists
- authorization exists
- persistence works
- error handling exists
- loading/empty states exist
- responsive behavior works
- tests exist
- tests pass
- lint passes
- typecheck passes
- build passes
- documentation is updated

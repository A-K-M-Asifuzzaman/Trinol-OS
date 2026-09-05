# ADR-0001 — Monorepo layout and stack

Status: Accepted (Phase 0)

## Context

MASTER_PROMPT §4–5 fixes the stack (Next.js + FastAPI + PostgreSQL) and sketches
a monorepo with `apps/`, `packages/shared`, `infrastructure/`, `docs/`,
`scripts/`. Two languages in one repository need a decision about tooling
boundaries.

## Decision

Single Git repository, two applications, **no shared package**.

- `apps/api` — Python 3.12, `uv` for dependency management and locking, `ruff`
  for lint and format, `mypy --strict` on `src/`.
- `apps/web` — Node 22, `pnpm`, TypeScript strict, ESLint + Prettier.
- No JS monorepo tool (Turborepo/Nx). There is exactly one JS package; a build
  orchestrator for one package is configuration with nothing to orchestrate.
- Cross-cutting commands live in a `Makefile` at the root (`make dev`,
  `make test`, `make lint`, `make check`) so a developer never has to remember
  which directory a command runs in.

Rejected: `packages/shared`. The only genuinely shared artefact is the API type
contract, and that is generated (see ADR-0005) rather than hand-maintained.

Rejected: two separate repositories. Atomic commits across an API change and its
frontend consumer are worth more here than independent release cadence, which
this team does not need.

## Consequences

- One PR can change schema, API and UI together, and CI verifies the whole thing.
- `uv` and `pnpm` are both fast and lockfile-strict; CI installs are reproducible.
- If the API is ever consumed by a second frontend, the generated-types step is
  duplicated rather than shared. Acceptable, and reversible.

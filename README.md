# Trinol OS

Trinol OS is TrinolIT's internal company operating system.

The first goal is to help TrinolIT manage:
- projects
- tasks
- leads
- clients
- meetings
- finance
- documents
- team activity

The long-term goal is to evolve it into a SaaS product for software agencies, startups, service companies, and SMEs.

## Agent Workflow

Shared instructions:
- AGENTS.md

Claude Code:
- CLAUDE.md
- PHASE_0_PROMPT.md
- CLAUDE_REVIEW_RESOLUTION.md

Codex:
- CODEX.md
- CODEX_PHASE_0_AUDIT.md
- CODEX_PHASE_REVIEW_TEMPLATE.md

Product specification:
- MASTER_PROMPT.md

Roadmap:
- ROADMAP.md

## Architecture

Phase 0 design (no product code yet):

- [ARCHITECTURE.md](docs/architecture/ARCHITECTURE.md) — system shape, modules, request path, frontend
- [DATABASE.md](docs/architecture/DATABASE.md) — ERD, tables, constraints, organization isolation
- [AUTH.md](docs/architecture/AUTH.md) — Firebase identity, local sessions, CSRF
- [RBAC.md](docs/architecture/RBAC.md) — roles, permission matrix, escalation guards
- [SECURITY.md](docs/architecture/SECURITY.md) — trust boundaries, top risks, headers, uploads
- [EMAIL.md](docs/architecture/EMAIL.md) — sender abstraction, templates, contact flow
- [TESTING.md](docs/architecture/TESTING.md) — test layers, security matrices, CI gates
- [DEPLOYMENT.md](docs/architecture/DEPLOYMENT.md) — environments, images, migrations, backups
- [docs/adr/](docs/adr/README.md) — 13 decision records
- [V1_SCOPE.md](docs/product/V1_SCOPE.md) — what V1 is and is not

## Recommended Workflow

1. Claude executes Phase 0 only.
2. Codex audits Phase 0.
3. Claude resolves valid P0/P1 findings.
4. Codex verifies.
5. Only then begin Phase 1.
6. Repeat the builder → reviewer → fix → verify loop for every phase.

Do not let Claude and Codex modify the same working tree simultaneously unless you are using isolated Git worktrees/branches.

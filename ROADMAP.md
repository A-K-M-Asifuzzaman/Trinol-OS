# Trinol OS Roadmap

Legend:
- [x] Complete
- [~] In progress
- [ ] Not started
- [!] Blocked

Gate rule:
Do not start a phase while a P0 or P1 finding is open in a dependency phase.

## Phase 0 — Architecture

Status: **APPROVED by Codex.** No product code was written.

- [x] Repository inspection
- [x] Product scope review
- [x] Domain boundaries — [ARCHITECTURE.md §3](docs/architecture/ARCHITECTURE.md)
- [x] ERD/database design — [DATABASE.md](docs/architecture/DATABASE.md)
- [x] Authentication strategy — [AUTH.md](docs/architecture/AUTH.md), [ADR-0013](docs/adr/0013-firebase-as-identity-provider.md)
- [x] Session strategy — [ADR-0002](docs/adr/0002-opaque-server-sessions.md)
- [x] RBAC design — [RBAC.md](docs/architecture/RBAC.md)
- [x] Organization isolation strategy — [ADR-0003](docs/adr/0003-single-db-org-scoping.md)
- [x] API conventions — [ADR-0005](docs/adr/0005-api-conventions-and-generated-types.md)
- [x] Frontend architecture — [ARCHITECTURE.md §5](docs/architecture/ARCHITECTURE.md)
- [x] Testing architecture — [TESTING.md](docs/architecture/TESTING.md)
- [x] Deployment architecture — [DEPLOYMENT.md](docs/architecture/DEPLOYMENT.md)
- [x] Security review — [SECURITY.md](docs/architecture/SECURITY.md)
- [x] ADRs — [docs/adr/](docs/adr/README.md), 13 records
- [x] V1 scope and trims — [V1_SCOPE.md](docs/product/V1_SCOPE.md), [ADR-0012](docs/adr/0012-v1-scope-trims.md)
- [x] Codex architecture audit
- [x] Resolve P0/P1 findings — composite tenant foreign keys, atomic rate
  limiting, invoice/payment locking, and race-safe invitation provisioning
  documented in the architecture and ADRs
- [x] Claude review of the audit resolution — all four accepted; three
  follow-on gaps closed (person columns reference `memberships` not `users`,
  `users.avatar_url` replaces an org-scoped file FK, public contact endpoint
  resolves its org from config). See [DATABASE.md §5.1](docs/architecture/DATABASE.md)
- [x] Verification round 2 — membership deletion semantics
  ([DATABASE.md §5.2](docs/architecture/DATABASE.md)) and an organization-aware
  FK for `organizations.logo_file_id`
- [x] Verification round 3 — added `UNIQUE (organization_id, id)` to all eight
  composite-FK-target tables (not just `file_objects`), plus a CI schema-
  integrity test so a single-column FK to an org-scoped table fails the suite
- [x] Final Codex approval — 3 verification rounds, all P0/P1 resolved

### Open decisions carried out of Phase 0

1. **Firebase sign-in methods** — **resolved: both email/password and Google**,
   invitation-gated, verified email required. Matches the design already in
   [ADR-0013](docs/adr/0013-firebase-as-identity-provider.md) and
   [AUTH.md §4](docs/architecture/AUTH.md); no change needed.

Answers still needed before Phase 5/6 respectively; none block Phase 1.

2. **Hosting target** — single VM (assumed, [ADR-0009](docs/adr/0009-deployment-single-host-compose.md)) or a PaaS split, which changes the same-origin cookie assumption.
3. **Invoice tax model** — one rate per invoice is assumed; per-line tax and VAT/GST numbers are not built.
4. **Google Calendar** — treated as not justified until asked ([ADR-0012](docs/adr/0012-v1-scope-trims.md)).

## Phase 1 — Foundation

Exit criteria: an invited user can sign in, land on a dashboard shell, and be
correctly refused everything their role does not permit — with the security
matrices green in CI.

- [ ] Monorepo skeleton, Makefile, `.env.example` ([ADR-0001](docs/adr/0001-monorepo-and-stack.md))
- [ ] Docker Compose: web, api, postgres, minio
- [ ] FastAPI app: config, structured logging, request_id, error envelope, `/health`, `/ready`
- [ ] SQLAlchemy base, `OrgScoped`, `OrgSession`, org-filter guard ([ADR-0003](docs/adr/0003-single-db-org-scoping.md))
- [ ] Alembic setup + first migration: organizations, users, memberships, sessions, invitations, activity_events, rate_limit_buckets
- [ ] Firebase Admin verification behind `IdentityVerifier`; token exchange endpoint ([ADR-0013](docs/adr/0013-firebase-as-identity-provider.md))
- [ ] Session issue/revoke, CSRF middleware, origin check
- [ ] Permission enum + role map + `require()` dependency + startup route audit ([ADR-0004](docs/adr/0004-roles-as-code.md))
- [ ] Escalation guards incl. last-owner protection ([RBAC.md §5](docs/architecture/RBAC.md))
- [ ] Activity/audit writer, append-only grants ([ADR-0006](docs/adr/0006-single-append-only-activity-table.md))
- [ ] Invitations: create, email, accept
- [ ] Team endpoints + Team page
- [ ] Next.js shell: login page, app layout, sidebar per §7 nav, dashboard shell with empty widgets
- [ ] shadcn/ui baseline, theme, four-state list primitives
- [ ] OpenAPI → `types.gen.ts` generation + CI diff check ([ADR-0005](docs/adr/0005-api-conventions-and-generated-types.md))
- [ ] Test foundation: fixtures, factories, two-org setup, the four security matrices ([TESTING.md §4](docs/architecture/TESTING.md))
- [ ] Seed script: org, 3 users across roles
- [ ] GitHub Actions CI: full gate list ([TESTING.md §6](docs/architecture/TESTING.md))
- [ ] Codex audit
- [ ] Resolve P0/P1 findings

## Phase 2 — Projects + Tasks
- [ ] Projects
- [ ] Tasks
- [ ] Kanban
- [ ] Milestones
- [ ] Project members
- [ ] Comments
- [ ] Activity
- [ ] Dashboard project widgets
- [ ] E2E foundation (Playwright)
- [ ] Codex audit
- [ ] Resolve P0/P1 findings

## Phase 3 — CRM
- [ ] Leads
- [ ] Pipeline
- [ ] Clients
- [ ] Follow-ups
- [ ] Lead conversion
- [ ] Website contact endpoint
- [ ] Email notifications
- [ ] Codex audit
- [ ] Resolve P0/P1 findings

## Phase 4 — Meetings + Calendar
- [ ] Meetings
- [ ] Notes
- [ ] Decisions
- [ ] Action items
- [ ] Action item → Task
- [ ] Google Calendar integration if justified
- [ ] Codex audit
- [ ] Resolve P0/P1 findings

## Phase 5 — Finance
- [ ] Income
- [ ] Expenses
- [ ] Invoices
- [ ] Payments
- [ ] PDF invoices
- [ ] Finance dashboard
- [ ] Backup restore rehearsal ([DEPLOYMENT.md §7](docs/architecture/DEPLOYMENT.md))
- [ ] Codex audit
- [ ] Resolve P0/P1 findings

## Phase 6 — Documents + Integrations
- [ ] Document references
- [ ] Google Drive integration
- [ ] GitHub integration
- [ ] Additional useful integrations
- [ ] Codex audit
- [ ] Resolve P0/P1 findings

## Phase 7 — Analytics
- [ ] Company analytics
- [ ] Project analytics
- [ ] Sales analytics
- [ ] Finance analytics
- [ ] Codex audit
- [ ] Resolve P0/P1 findings

## Phase 8 — AI
- [ ] Meeting summarization
- [ ] Action extraction
- [ ] Company assistant
- [ ] RAG / semantic company search
- [ ] Lead scoring
- [ ] Project risk intelligence
- [ ] AI audit
- [ ] Resolve P0/P1 findings

## Technical debt ledger

Deliberate shortcuts, each with its upgrade trigger. Recorded so "later" does
not mean "never".

| Shortcut | Where | Upgrade when |
|---|---|---|
| Offset pagination | ADR-0005 | a list exceeds ~50k rows |
| Fixed-window rate limit in Postgres | ADR-0010 | the public endpoint takes real traffic |
| No persistent email outbox | ADR-0010 | Phase 5 invoice delivery |
| Fractional board positions | DATABASE.md | precision exhausted; add a rebalance job |
| Single activity table | ADR-0006 | ~50M rows; partition by month |
| Proxied uploads | ADR-0008 | files over ~25 MiB or API host saturates |
| App-layer org scoping, not RLS | ADR-0003 | V4 multi-tenant SaaS |
| Session revocation reconciled on exchange + daily sweep | AUTH.md §8 | near-instant revocation needed |

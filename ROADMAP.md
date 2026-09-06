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

- [x] Monorepo skeleton, Makefile, `.env.example` ([ADR-0001](docs/adr/0001-monorepo-and-stack.md)) — Stage 1, `c639bfb`. minio deferred (no upload code until a phase needs it; see technical debt ledger)
- [x] FastAPI app: config, structured logging, request_id, error envelope, `/health` — Stage 2, `fe9f0d5`. `/ready` completed in Stage 3
- [x] SQLAlchemy base, `OrgScoped`, `OrgSession`, org-filter guard ([ADR-0003](docs/adr/0003-single-db-org-scoping.md)) — Stage 3, `f3ec0dc`; guard covers select/update/delete and `OrgSession.add()` rejects a mismatched org id (fixed post-review, `621fa7c`)
- [x] Alembic setup + first migration: organizations, users, memberships, sessions, invitations, activity_events, rate_limit_buckets — Stage 3, `f3ec0dc`, two-role split (`trinol_migrator`/`trinol_app`), `alembic check` clean
- [x] Firebase Admin verification behind `IdentityVerifier`; token exchange endpoint ([ADR-0013](docs/adr/0013-firebase-as-identity-provider.md)) — Stage 4, `81b6dae`. Codex review: Origin/Referer check on the exchange endpoint (`58a993e`), contact-endpoint origin exception (`e195cf0`, `e6e48d2`). **Approved.**
- [x] Session issue/revoke, CSRF double-submit token, `GET`/`DELETE /api/v1/auth/session`, `DELETE /api/v1/auth/sessions` — Stage 5, `70fd59f`. Corrected a Phase 0 design error found while implementing: `csrf_hash` couldn't satisfy AUTH.md §6's "raw value returned from GET" requirement (one-way hash), renamed to plaintext `csrf_token` (migration 0002). CSRF check is a global FastAPI dependency (`modules/identity/csrf.py`), not ASGI middleware like the origin check, so it participates in `app.dependency_overrides` for tests. **Approved.**
- [x] Permission enum + role map + `require()` dependency + startup route audit ([ADR-0004](docs/adr/0004-roles-as-code.md)) — Stage 6, `50611c3`. Consolidated the duplicate `MembershipRole`/`Role` enums into one (`core/authz/permissions.py`) found while wiring this up. Startup audit recurses into `include_router`-added routes (this FastAPI version wraps them in an internal `_IncludedRouter`, not a flat list — confirmed by inspection). Fixed a pre-existing test-pollution bug in Stage 2's exception-handler test (mutated the shared `app` singleton, leaking a route into every later test that inspects `app.routes`).
- [x] Escalation guards incl. last-owner protection ([RBAC.md §5](docs/architecture/RBAC.md)) — Stage 6, `50611c3`. Added a defense-in-depth precondition beyond the 6 numbered guards (actor must be ADMIN/OWNER outright) — guard 3 alone doesn't stop a MANAGER/MEMBER calling the service directly. Concurrent last-owner demotion tested with two genuinely independent DB connections (not the shared per-test transaction), verified stable across repeated runs. Codex review: shared services also didn't verify the actor belongs to `organization_id` (`593f89f`). **Approved.**
- [x] Activity/audit writer, append-only grants ([ADR-0006](docs/adr/0006-single-append-only-activity-table.md)) — Stage 7, `acee056`. Retrofitted the activity-event writes deferred from Stages 4 and 6 (login success/rejection, role change, removal). Found and documented a caveat AUTH.md didn't have: `activity_events.organization_id` is NOT NULL, so a rejection with no determinable organization (unknown identity, no invitation) is logged, not written to the table — only rejections where an org is actually known get an audit row. Found and fixed a real concurrency bug while adding the guard-6 write: `change_role`/`remove_member` didn't roll back on an exception raised after taking the organization's `FOR UPDATE` lock, reproduced as a genuine hang once a concurrent transaction needed the same row (activity_events' FK check). Fixed with rollback-on-exception around both functions. Codex review: that same premature-commit pattern applied to the *success* path too — `revoke_org_sessions` committed internally, durably persisting the role/status change before guard 6's audit event was written, breaking ADR-0006's same-transaction guarantee if the audit write or final commit then failed. Made `revoke_org_sessions` non-committing so the calling function is the sole transaction boundary, with a regression test that forces an audit failure and confirms the business change rolls back too (`969726b`). **Approved.**
- [x] Invitations: create, email, accept — Stage 8, pending commit. Email abstraction (`platform/email/`: `EmailSender` protocol, console/memory/SMTP backends, Jinja templates) per [EMAIL.md](docs/architecture/EMAIL.md). `invitation_service.py` guards mirror `membership_service.py`'s actor checks, plus reject-if-already-a-member and reject-duplicate-open-invitation. No separate accept endpoint — `POST /auth/session` already completes provisioning (ADR-0013); `GET /api/v1/invitations/{token}` is a public, unscoped, mutation-free preview for the invitation-landing page. Found and fixed while building the render step: `select_autoescape(("jinja",))` matches on file extension, so it would have escaped the plain-text email body too (both templates end `.jinja`) — switched to a name-based check (`.html.` substring) instead, with a regression test.
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
| minio omitted from Phase 1 Compose | Stage 1 plan (`docs/adr/0001-monorepo-and-stack.md`'s sibling decisions) | whichever phase first adds file uploads (task attachments, Phase 2) |
| Org-scope guard covers select/update/delete, not bulk Core `insert()` | `core/db/org_session.py` | a bulk insert is ever written instead of `session.add()`/`OrgSession.add()` |
| Contact-endpoint origin exception is a single hardcoded special case, not a general allowlist | `core/security/origin_check.py` | a second endpoint ever needs a non-default origin |
| Auth rejections with no determinable organization are logged, not audited | `session_service.py` (AUTH.md §5) | never — `activity_events.organization_id` is NOT NULL by design; would need a schema change (a nullable org column, or a separate unattributed-events table) to close |

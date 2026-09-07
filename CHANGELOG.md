# Changelog

All notable changes to Trinol OS. Format loosely follows Keep a Changelog.

## [Unreleased]

### Added — Phase 0 (architecture only, no product code)
- Architecture docs: ARCHITECTURE, DATABASE, AUTH, RBAC, SECURITY, EMAIL,
  TESTING, DEPLOYMENT.
- 13 ADRs covering stack, sessions, organization isolation, authorization,
  API conventions, activity/audit, money, storage, deployment, omitted
  infrastructure, soft delete, V1 scope trims, and Firebase as identity provider.
- V1 scope document and roadmap with per-phase exit criteria and a technical
  debt ledger.

### Changed — Phase 0 audit resolution
- Documented composite organization-scoped foreign keys for cross-tenant
  relationship integrity.
- Specified atomic PostgreSQL rate-limit updates.
- Removed persisted `OVERDUE` invoice status and required invoice-row locking
  for concurrent payment recording.
- Made invited-user provisioning and invitation consumption one locked
  transaction.

### Changed — Claude review of the audit resolution
- Extended composite tenant foreign keys to person columns: assignee, owner,
  author and participant columns reference `memberships (organization_id,
  user_id)`, closing the cross-org assignment the service-layer exception left
  open. `activity_events.actor_id` and `invitations.invited_by` stay global so
  history survives a departure.
- `users.avatar_file_id` → `users.avatar_url`; a global user cannot hold an FK
  into org-scoped `file_objects`.
- Public contact endpoint resolves `organization_id` from configuration,
  validated at startup.

### Changed — Phase 0 verification round 2
- Documented membership deletion semantics (DATABASE.md §5.2): membership rows
  are never deleted by a product flow — removal is `status = INACTIVE`.
  Referential actions are `RESTRICT` on assignment and authorship columns,
  `CASCADE` for `project_members` and `sessions`. Deactivation revokes sessions
  and reports open assignments for manual reassignment; GDPR erasure is an
  operator procedure that anonymizes `users` and preserves the graph.
- `organizations.logo_file_id` uses its own `id` as the tenant key:
  `FOREIGN KEY (id, logo_file_id) REFERENCES file_objects (organization_id, id)`.

### Changed — Phase 0 verification round 3
- Added the `UNIQUE (organization_id, id)` constraint PostgreSQL requires on
  every table targeted by a composite FK — `projects`, `clients`, `tasks`,
  `milestones`, `meetings`, `invoices`, `leads`, `file_objects` — each named at
  its table definition rather than only asserted in §5.1. Fixes the
  `organizations.logo_file_id` migration failure Codex identified, which
  applied to seven other tables as well.
- Added a schema-integrity CI test (TESTING.md) that reads
  `information_schema` and fails on any single-column FK between two
  org-scoped tables.

## Phase 0 — APPROVED

Codex verification, round 4: no remaining P0/P1 findings. Verdict APPROVE.
Firebase sign-in methods confirmed as both email/password and Google —
matched the design already in place, no changes required.

## Phase 1 — Foundation (in progress)

Full history and per-stage Codex review notes live in ROADMAP.md; this is
the condensed release-note version. See ROADMAP.md's technical debt ledger
for open shortcuts.

### Added — Stages 1–3: repo skeleton and database foundation
- Monorepo scaffold (`apps/api`, `apps/web`), Makefile, Docker Compose,
  `.env.example`.
- FastAPI app: structured JSON logging with redaction, request-id
  middleware, the `{error: {code, message, request_id, details}}` envelope,
  `/health`/`/ready`.
- `OrgScoped`/`OrgSession` and the `do_orm_execute` guard that fails any
  select/update/delete against an org-scoped table with no
  `organization_id` predicate (ADR-0003). Alembic + the initial migration
  (organizations, users, memberships, sessions, invitations,
  activity_events, rate_limit_buckets), with the `trinol_migrator`/
  `trinol_app` two-role split ADR-0006 requires.

### Added — Stages 4–7: auth, sessions, RBAC, activity
- Firebase Admin token verification behind an `IdentityVerifier` Protocol;
  `POST /api/v1/auth/session` exchanges a Firebase ID token for an opaque
  server-side session (ADR-0013). Origin/Referer checked on every unsafe
  request (login-CSRF).
- Session lifecycle (`GET`/`DELETE /api/v1/auth/session`,
  `DELETE /api/v1/auth/sessions`) and double-submit CSRF verification.
- `Role`/`Permission`/`ROLE_PERMISSIONS` (RBAC.md §2) and a startup audit
  that fails app boot if any route has neither `require(...)` nor
  `@public`. The six escalation guards (RBAC.md §5), including a
  `FOR UPDATE` lock on the organization row for the last-owner check.
- One append-only `activity_events` table serving both the feed and the
  audit log (ADR-0006), with `UPDATE`/`DELETE` revoked from the runtime
  Postgres role.

### Added — Stage 8: invitations
- Email abstraction (console/memory/SMTP backends, Jinja templates) and
  `invitation_service.py` (create, list, public token preview). No
  separate accept endpoint — `POST /auth/session` already completes
  provisioning.
- Codex review: fixed a concurrent-duplicate-invitation race (organization
  row lock), inconsistent expiry handling across two queries, a bare-array
  list response (now paginated per ADR-0005), and invitations created for
  already-departed members that could never be consumed.

### Added — Stage 9: team endpoints + generated types
- `GET`/`GET {id}`/`PATCH /api/v1/memberships`, backed by a
  `team_service.py` that assembles Membership+User for the team page's
  fields. `openapi-typescript` generates `apps/web/lib/api/types.gen.ts`,
  committed and diff-checked in `make check`.
- Codex review: fixed a non-atomic `PATCH` (role and status each mapped to
  their own commit — now exactly one of the two per request) and a
  pagination tie-breaker on the team listing.

### Added — Stage 10: Next.js frontend shell
- Next.js tooling (tsconfig, ESLint flat config, Tailwind, Vitest), hand-
  written shadcn-style primitives, the four-state list primitive
  (ARCHITECTURE.md §5), login page (Firebase JS SDK loaded only there),
  app shell with the MASTER_PROMPT §7 nav tree, server-rendered dashboard
  with a live team-count tile, and a client-rendered Team page (MSW-tested
  against all four states).
- Codex review: fixed three P1s — the API client called `localhost:8000`
  directly instead of a same-origin relative path (CORS is disabled by
  design; this could never have worked in a real browser), Finance
  navigation was visible to every role instead of ADMIN+/OWNER only
  (RBAC.md §2), and the app shell had no mobile layout at all. Added a
  `next.config.mjs` `/api/*` rewrite, server-resolved role passed to the
  sidebar, and a collapsible mobile nav.

### Added — Stage 11: test foundation checkpoint
- `two_orgs` fixture (two organizations, each with a full role roster) and
  `login_as_existing`; all five TESTING.md §4 security matrices now exist,
  including a new authentication matrix and a formal authorization matrix
  with a meta-assertion that fails if a route has no row.
- Building that matrix caught a real bug: `GET /api/v1/invitations`
  declared a permission granted to every role, but its service function
  has always enforced ADMIN+ only. Fixed to declare the permission it
  actually enforces.

### Added — Stage 12: seed script
- `scripts/seed.py`: one organization (`trinolit`) with three placeholder
  users (Founder/Developer/Designer) under the real company domain.
- Codex review: the idempotency test's cleanup tracked pre-existence only
  at the organization level, so a partially-seeded org or an unrelated
  pre-existing user at a seed email could be mishandled. Fixed to track
  pre-existence per entity (org, each user, each membership).

### Added — Stage 13: CI
- `.github/workflows/ci.yml`: four jobs (backend, frontend, OpenAPI diff,
  security) covering TESTING.md §6's full gate list against a real
  Postgres service container.
- Found a real, pre-existing vulnerability while wiring up the security
  job: `next`'s bundled internal `postcss` copy carries four disclosed
  CVEs; our own direct `postcss` dependency was never affected. Confirmed
  a pnpm override can't reach next's internally-pinned copy (it changed
  nothing, tested with and without it), so the CI gate documents and
  allowlists this one upstream-only exception rather than silently
  passing or permanently blocking on it.
- Checked every pinned GitHub Action version against the live API rather
  than trusting cached knowledge: all five were multiple majors behind,
  migrating off the Node 20 Actions runtime GitHub removes from hosted
  runners on 2026-09-16.

# Changelog

All notable changes to Trinol OS. Format loosely follows Keep a Changelog.

## [Unreleased]

### Changed — full-app UI/UX upgrade

- Reworked the application into a cohesive Trinol-branded operations workspace:
  carbon navigation frame, warm high-clarity canvas, signal accent, stronger
  hierarchy, denser data surfaces, and responsive route-aware navigation.
- Upgraded shared controls, form fields, tables, badges, loading/empty/error
  states, Kanban and pipeline boards, dashboard, reports, finance, assistant,
  and login. No new frontend dependency or backend behavior was introduced.
- Added accessible focus treatments and reduced-motion handling. All 104
  frontend tests, lint, typecheck, and the production build pass.
- Cleared the local OpenAI key at the product owner's request; no real-provider
  service or E2E flow was started during this work.

### Fixed — AI disabled-mode isolation and error handling

- A missing OpenAI key previously raised while FastAPI resolved the route
  dependency, before the service could apply organization-scoped resource
  checks. The dependency now returns a zero-network unavailable client: hidden
  resources retain their required 404 response, while an authorized operation
  that actually needs AI receives a structured 503. The complete 1,310-test
  backend suite passes with the key empty.

## Phase 8 — AI — APPROVED

- Added OpenAI-backed meeting summaries and action extraction, lead scoring,
  deterministic project-risk intelligence, and a company assistant over
  permission-filtered pgvector retrieval. Financial rows are never embedded;
  authorized finance figures come only from the existing deterministic
  aggregate service.
- Added the AI frontend surfaces, role/isolation matrices, representative seed
  data, and a real-provider E2E flow. The normal 1,309-test backend suite uses
  only the deterministic fake client and makes zero OpenAI network calls.
- Final audit fixes batch each bounded reindex into one embedding request,
  suppress stale project-risk narratives, atomically upsert concurrent AI
  caches, record the project-risk generating actor, and harden the assistant's
  treatment of instructions inside retrieved content as untrusted data.
- Phase 8 is the final feature phase in MASTER_PROMPT §39. A cohesive full-app
  UI/UX upgrade is tracked separately and deliberately starts only after this
  feature build is closed.

## Phase 2 — Projects + Tasks

Full history and per-stage Codex review notes live in ROADMAP.md; this is
the condensed release-note version.

### Added — Phase 2: work schema and project management
- Added the work-module schema for projects, project members, milestones,
  tasks, comments, and checklist items with composite organization-scoped
  foreign keys and supporting indexes.
- Added project CRUD and project-member roster management with role and
  ownership checks, archive semantics, pagination, and generated API types.
- Added task CRUD, a Kanban board endpoint with a capped, grouped-by-status
  response, task comments and checklist items, and file attachments backed
  by a `FileStorage` abstraction with local and S3-compatible backends.
- Codex review fixes cover concurrent project-code conflicts, merged PATCH
  validation, decimal-string budgets, per-route ownership/isolation tests,
  refreshed trigger-generated `updated_at` values, and audit events on
  every hard-delete path (tasks, comments, checklist items, attachments).

### Fixed — schema-integrity CI gate was silently non-functional since Phase 1
- The composite-foreign-key regression test (added Phase 1 Stage 3,
  TESTING.md §4 item 5) queried `information_schema.constraint_column_usage`,
  whose own view definition only returns rows to a role with `USAGE` on the
  constrained table's *owning* role. `trinol_app` — the role the entire test
  suite and CI run as — is deliberately not a member of `trinol_migrator`
  (ADR-0006's two-role split), so this view has returned zero rows to every
  run of this test for the whole project's history, making both of its
  assertions vacuously true. Found while adding a Stage 6 regression test
  that asserts a specific FK positively exists, rather than only "no
  violations found" — a check an empty result set satisfies by accident.
  Rewritten to query `pg_constraint`/`pg_attribute`/`pg_class` directly,
  which carry no such owner-role restriction; also fixed a second,
  independent bug the same rewrite exposed (the original query's join
  produced a cross product across both sides' columns before aggregation,
  silently duplicating entries for any FK with more than one column on
  either side). Verified empirically both ways: confirmed the fixed query
  now genuinely rejects a deliberately-added single-column FK between two
  org-scoped tables (reverted immediately after).

### Fixed — `make seed`'s CLI entry point crashed since Phase 2 Stage 6
- `scripts/seed.py` never imports `trinol.platform.models`, so SQLAlchemy's
  mapper registry never learns about `file_objects` — flushing the very
  first `Organization` row then crashes with `NoReferencedTableError`
  trying to resolve `organizations.logo_file_id`'s composite FK to it.
  Invisible in the test suite because every test importing `trinol.main`
  (transitively, via `tests/conftest.py`) registers `platform.models` as a
  side effect before `seed()` ever runs — the standalone `python -m
  trinol.scripts.seed` path has no such import chain. `migrations/env.py`
  already carries the identical one-line fix for the identical reason;
  applied the same fix here. Found and confirmed by actually running
  `make seed` against a real local Postgres, not by reading the code —
  reproduced by reverting the fix (`git stash`) and confirming the crash
  returns.
- A related bug in `tests/unit/test_seed_idempotent.py`'s cleanup helper:
  it tracked only Organization/User/Membership, so once `seed()` also
  creates Projects (`owner_id` is a composite FK to `memberships`), cleanup
  deleting a membership before its project hit
  `fk_projects_org_owner_memberships` — the same *shape* of bug Phase 1
  Stage 12's Codex review already found and fixed once for
  Organization/User, now recurring one entity layer down. Extended the
  same per-entity snapshot/cleanup tracking to projects, project members,
  and tasks.

### Added — Phase 2: frontend and E2E foundation
- Added Projects and Tasks pages, a Kanban board with native HTML5
  drag-and-drop, `/tasks/my`, and real dashboard task/project counts.
- Added a Playwright E2E foundation: a gated, non-production test-only
  `E2EIdentityVerifier` (`E2E_TEST_MODE`, double-checked against `app_env`
  at the call site) lets an externally-running server authenticate a
  Playwright browser without real Firebase credentials, and a smoke spec
  covers login, project creation, task creation, and a Kanban drag/drop.

### Fixed — a UI-created task could never appear on any Kanban board
- The task-creation form never collected a `project_id`, so every task
  made through the app landed unassigned — and the board endpoint groups
  strictly by `project_id`. "Create a task, move it on the board"
  (TESTING.md §5) was structurally impossible through the UI. Found while
  actually driving the app end to end for the Playwright smoke spec, not
  by reading the code. Added a project picker to the create-task form.

### Fixed — CSRF token didn't survive a fresh page load
- The client's CSRF token (AUTH.md §6) is deliberately in-memory only and
  was set exactly once, right after the login form's own sign-in call —
  correct for an uninterrupted SPA session, but any full page load
  afterward (a hard refresh, a new tab, or a test driver's `page.goto()`)
  wiped it with nothing to restore it, so the next state-changing request
  from an already-authenticated session failed with "Invalid or missing
  CSRF token." Reproduced directly by the Playwright smoke spec before
  being fixed. The authenticated layout now rehydrates the token from the
  session-info endpoint on every load, not just the login form's own.

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

## Phase 2 — APPROVED

Codex final verification (Stage 11): "approved... no P0/P1/P2 findings,"
independently re-verifying the E2E identity verifier's production gate,
CSRF rehydration, project-linked task creation, the full test suite (510
backend, 22 frontend), and `make check` end to end. All 11 stages
independently reviewed and re-verified per-stage throughout, not as one
end-of-phase pass — full history in ROADMAP.md.

## Phase 0 — APPROVED

Codex verification, round 4: no remaining P0/P1 findings. Verdict APPROVE.
Firebase sign-in methods confirmed as both email/password and Google —
matched the design already in place, no changes required.

## Phase 1 — Foundation

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
- Codex review: fixed two P1s. `pnpm audit --prod` skipped devDependencies,
  hiding a critical `vitest` advisory and several `vite`/`esbuild` ones —
  fixed for real with a `vitest` 2→5 major upgrade (a real fix existed,
  unlike the postcss/next case) rather than allowlisted. The postcss
  allowlist matched on package name alone, which would silently pass any
  future postcss advisory — tightened to the exact four known advisory
  IDs and the exact dependency path.

## Phase 1 — APPROVED

Codex final verification (Stage 13): "Phase 1 is feature-complete ...
there are no remaining Codex P0/P1 blockers." All 13 stages independently
reviewed and re-verified per-stage throughout, not as one end-of-phase
pass — full history in ROADMAP.md.

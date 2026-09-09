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

Status: **APPROVED by Codex.** All 13 stages complete and independently reviewed.

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
- [x] Invitations: create, email, accept — Stage 8, `33c16d4`. Email abstraction (`platform/email/`: `EmailSender` protocol, console/memory/SMTP backends, Jinja templates) per [EMAIL.md](docs/architecture/EMAIL.md). `invitation_service.py` guards mirror `membership_service.py`'s actor checks, plus reject-if-already-a-member and reject-duplicate-open-invitation. No separate accept endpoint — `POST /auth/session` already completes provisioning (ADR-0013); `GET /api/v1/invitations/{token}` is a public, unscoped, mutation-free preview for the invitation-landing page. Found and fixed while building the render step: `select_autoescape(("jinja",))` matches on file extension, so it would have escaped the plain-text email body too (both templates end `.jinja`) — switched to a name-based check (`.html.` substring) instead, with a regression test. Codex review found four P1s, all fixed: (1) `create_invitation`'s check-then-insert had no lock, letting two concurrent requests for the same org+email both succeed — fixed by extracting membership_service's guard-4 `FOR UPDATE` organization lock into a shared `organization_lock.py` and taking it before the checks, wrapped in the same rollback-on-exception pattern Stage 7 established; concurrency regression test mirrors the last-owner-demotion test's two-independent-connections approach. (2) `list_open_invitations` and the session-provisioning invitation lookup both ignored `expires_at`, so an expired row could shadow a valid one — the list query now filters `expires_at > now()`, and the provisioning query orders by `expires_at DESC` so a valid invitation (whose expiry is always later than an expired one's) sorts first. (3) `GET /api/v1/invitations` returned a bare array — now `{items, total}` with `limit`/`offset` (default 50, cap 200) per ADR-0005. (4) Creating an invitation only checked for an ACTIVE membership, but `_resolve_or_provision_user`'s existing-user branch never re-checks invitations on a returning login — an invitation for an INACTIVE/ON_LEAVE former member could never be consumed. Broadened the guard to reject inviting anyone with *any* existing membership row in the org, regardless of status (see technical debt ledger — no reactivation path exists yet). Fixes: `7370cfc`. **Approved.**
- [x] Team endpoints: `GET`/`GET {id}`/`PATCH /api/v1/memberships` — Stage 9, `3c477b9`. `team_service.py` assembles Membership+User (no ORM relationship joins them anywhere in this codebase — same two-query pattern `invitation_service.py` already uses) for the MASTER_PROMPT §17 fields (name, email, avatar, role, job_title, status, joined_at). `GET` routes are readable by every role (`TEAM_READ` is a MEMBER-tier permission); `PATCH` wraps the existing `change_role`/`remove_member` from Stage 6/7 rather than reimplementing their guards — accepts `role` and/or `status` (only `INACTIVE` is a valid status value; anything else is an honest 422, since no guarded reactivation path exists yet). Extracted two more helpers out of `membership_service.py` into shared modules for reuse here, matching the Stage 8 fix's precedent: `get_membership_in_org` → `membership_lookup.py`. `tests/security/test_authz_matrix.py` and `test_isolation_matrix.py` (RBAC.md §6, TESTING.md §4.3) start here, team routes only — Stage 11 adds the meta-assertion that fails when a future route has no row. Codex review: PATCH accepted `role` and `status` together, which ran `change_role` then `remove_member` as two separately-committing calls with no shared transaction — a failure in the second would leave the first's mutation durably persisted despite the request reporting one failure. Fixed at the schema layer (`MembershipUpdateRequest` now requires *exactly* one of `role`/`status`, not "at least one") rather than merging the two guarded operations into one transaction — each accepted request now always maps to exactly one atomic service call; a client wanting both makes two PATCH requests. Regression tests cover both-fields (422) and neither-field (422). Fix: `1f2cd9e`. **Approved.** Codex re-review also flagged two nonblocking P2s: a pagination tie-breaker (`Membership.joined_at` alone isn't a unique sort key — two memberships created in the same instant, e.g. by a seed script, could tie and let an OFFSET/LIMIT page skip or repeat a row; fixed by adding `Membership.id` as a secondary sort key, with a regression test forcing a tie — `dd6e14c`) and a "CI documentation mismatch" whose exact text didn't reach this log — logged in the technical debt ledger pending the specific finding.
- [x] OpenAPI → `types.gen.ts` generation + CI diff check ([ADR-0005](docs/adr/0005-api-conventions-and-generated-types.md)) — Stage 9, `3c477b9`. `pnpm install` + `make openapi` run clean; `apps/web/lib/api/types.gen.ts` and `pnpm-lock.yaml` committed. The rest of the frontend gate (`tsc`, `eslint`, `vitest`, `next build`) can't run yet — `apps/web` is still Stage 1's directory skeleton with no `tsconfig.json`, ESLint/Tailwind config, or pages; that scaffolding is Stage 10's scope, not this stage's.
- [x] Team page — Stage 10, `e20cd7d`. `app/(app)/team/page.tsx`, deliberately client-rendered against TanStack Query rather than ARCHITECTURE.md §5's server-rendered-by-default: the proof criterion needs all four list states unit-testable against MSW, which needs a client-side fetch. Reasoned, documented departure — not an oversight.
- [x] Next.js shell: login page, app layout, sidebar per §7 nav, dashboard shell with empty widgets — Stage 10, `e20cd7d`. Login page is React Hook Form + Zod, calling `lib/firebase/client.ts` (loaded only there, per AUTH.md §10) then `POST /auth/session`. Sidebar renders MASTER_PROMPT §7's full nav tree; only Team links anywhere, everything else is a disabled label until its phase builds the page. Dashboard stays server-rendered (the default) with one real widget — the team-count tile (decision 8), forwarding the incoming cookie to `GET /memberships`.
- [x] shadcn/ui baseline, theme, four-state list primitives — Stage 10, `e20cd7d`. Hand-wrote `components/ui/{button,skeleton,badge}.tsx` (Tailwind + clsx/tailwind-merge, both already installed) instead of running the shadcn CLI, to avoid a component-registry network fetch inside an agent sandbox — same copy-paste-owned-code philosophy, just written by hand; add real shadcn scaffolding later if its specific components are needed. `components/list/{loading,empty,error}-state.tsx` is the four-state primitive ARCHITECTURE.md §5 requires. `make check`'s full chain (backend + frontend + the OpenAPI diff check) is green end to end for the first time in this project. Worked around a Node 25 test-environment quirk (msw's Node-side cookie jar touches the native global `localStorage`, which throws without `--localstorage-file`) with an in-memory shim in `tests/setup.ts` — Docker/CI target Node 22 regardless (decision 4), so this is a test-environment fix, not a product one.

  Codex review found three P1s, all fixed: (1) the API client defaulted every browser request to `http://localhost:8000` with no `/api/*` rewrite and CORS deliberately disabled server-side (SECURITY.md §3) — meaning login and every Team request would fail outright in a real browser, and in Docker `localhost:8000` inside the `web` container doesn't even reach `api`. Fixed by adding a `next.config.mjs` rewrite plus a server-only `INTERNAL_API_URL` env var (`docker-compose.yml` sets it to `http://api:8000`); the browser now only ever calls relative `/api/*` paths, same-origin, exactly as ARCHITECTURE.md §1 specifies. (2) The sidebar rendered Finance unconditionally for every role, violating RBAC.md §2's "Finance is invisible to MEMBER and MANAGER — not merely hidden in navigation" — fixed by resolving the session role server-side in `app/(app)/layout.tsx` and filtering the Finance nav group in `Sidebar` for anything but ADMIN/OWNER, with a regression test covering all four roles plus an unresolved-role fallback. (3) The app shell had no mobile layout at all (AGENTS.md's own "a feature is not done" checklist requires responsive behavior) — added a `components/nav/app-shell.tsx` client wrapper with a collapsible mobile nav toggle, and wrapped the Team table in a horizontally-scrolling container. Fixes: `11e2d24`. **Approved.**
- [x] Test foundation: fixtures, factories, two-org setup, the five security matrices ([TESTING.md §4](docs/architecture/TESTING.md)) — Stage 11, `5ef1ceb`. `tests/conftest.py`'s `two_orgs` fixture provisions two organizations, each with a full OWNER/ADMIN/MANAGER/MEMBER roster, for tests that need every role in one org and/or a second org to probe across; `tests/helpers.py` gained `login_as_existing` so a test can log in as one of that fixture's already-created memberships instead of creating a parallel throwaway one. All five TESTING.md §4 matrices now exist: (1) `test_authn_matrix.py` (new) — every non-public route without a session → 401, derived from the live route table so a new route can't silently skip it; (2) `test_authz_matrix.py` — a genuine table (route, required `Permission`, example payload) with a meta-assertion that fails if any permission-gated route has no row (RBAC.md §6's own wording), derived from the same `require()` markers `startup_audit.py`'s boot-time check reads rather than a hand-maintained list that could drift; (3) `test_isolation_matrix.py` — broadened with an all-four-roles-in-org-B check using `two_orgs`; (4) `test_escalation.py` (already existed, Stage 6/7); (5) `test_schema_integrity.py` (already existed, Phase 0). Promoted two more startup_audit.py internals to public, reusable functions for this: `_iter_api_routes` → `iter_api_routes`, plus a new `get_required_permission()` in `core/authz/require.py` (removing a duplicated marker-string constant). Building the formal authz matrix caught a real bug: `GET /api/v1/invitations` declared `require(Permission.TEAM_READ)` (granted to every role) but its service function has always enforced ADMIN+ only (`_ensure_actor_is_admin`) — the route's documented/generated-OpenAPI contract was silently wrong. Fixed to declare `Permission.MEMBER_INVITE`, matching what it actually enforces (and its sibling `POST` route). 157 backend tests pass (was 126); `make check`'s full chain, including the OpenAPI diff, is clean. **Approved.**
- [x] Seed script: org, 3 users across roles — Stage 12, `2503e53`. `scripts/seed.py` (decision 6): one organization (`trinolit`), three placeholder users named after MASTER_PROMPT §36's role hints (Founder/Developer/Designer) under the real `@trinolit.com` domain — Founder is OWNER, the other two MEMBER. Structural placeholders only: no Firebase account exists for them yet, so nobody can sign in as one until real accounts are created and `firebase_uid` updated to match. MASTER_PROMPT §36's fuller seed set (clients, projects, tasks, leads, invoices, meetings) waits for the phases that build those tables — out of scope here. Idempotent, matched on the org's slug, each user's email, and the (org, user) membership pair; verified by actually running `make seed` twice against the real local DB before writing the test, not just asserting it in the abstract. `tests/unit/test_seed_idempotent.py` calls `seed()` directly (it manages its own session, same as any standalone CLI) and only cleans up the rows it created itself — checked whether the org already existed *before* the test ran, since ROADMAP's own verification sequence runs `make seed` before `make check`, and a naive unconditional cleanup would have silently deleted a developer's real local seed data as a side effect of running the test suite (caught by actually running the full suite after a real `make seed` and checking the row survived, not by reasoning about it). 158 backend tests pass (was 157); `make check`'s full chain, including the OpenAPI diff, is clean.

  Codex review: that cleanup tracked pre-existence only at the *organization* level, so (a) an org that already existed but was missing one seed user/membership got the new rows created but never cleaned up (cleanup was skipped entirely once the org matched), and (b) a seed email that happened to already belong to some unrelated pre-existing user had that user deleted by cleanup's blanket `email.in_(...)` delete. Fixed by tracking existence per entity — the organization, each of the three users, and each of the three memberships, independently — so cleanup only ever removes what wasn't there before calling `seed()`. Two new regression tests cover exactly the two scenarios above (partial pre-existing org state; a pre-existing, unrelated user at a seed email), each verified against the real local DB, including deliberately reverting to the old org-level-only check and confirming both new tests fail against it before restoring the fix. 160 backend tests pass (was 158). Fix: `e3c596c`. **Approved.**
- [x] GitHub Actions CI: full gate list ([TESTING.md §6](docs/architecture/TESTING.md)) — Stage 13, `4140332`. `.github/workflows/ci.yml`, four parallel jobs: `backend` (ruff, mypy --strict, alembic upgrade-head on an empty DB then downgrade -1/upgrade head, `alembic check`, pytest — all against a real `postgres:16-alpine` service container with the same `trinol_migrator`/`trinol_app` two-role split as local dev), `frontend` (eslint, prettier --check, tsc --noEmit, vitest, next build), `openapi-diff` (regenerates `types.gen.ts` and fails on any diff — ADR-0005; needs no live DB, since `app.openapi()` only needs `Settings` to construct), `security` (gitleaks, pip-audit, `pnpm audit` — TESTING.md §6 says "npm audit" generically, but this project only ever uses pnpm, so pnpm's own audit is the correct concrete gate). Verified every actually-runnable piece locally before considering this done: `uv export`/`uv run --with pip-audit pip-audit --skip-editable` (the `-r requirements.txt` form crashed building an ephemeral venv in local sandbox testing — switched to auditing the synced venv directly), the `pnpm audit --json` + `jq` allowlist script (tested both the pass and fail path by hand), and — a genuinely important catch — checked every pinned Action version against the GitHub API rather than trusting training-data versions: all five (`actions/checkout`, `astral-sh/setup-uv`, `pnpm/action-setup`, `actions/setup-node`, `gitleaks/gitleaks-action`) had shipped major version bumps migrating off the Node 20 Actions runtime, which GitHub fully removes from hosted runners on 2026-09-16 — days after this stage was built. Using the stale versions from memory would have shipped a workflow already close to broken.

  Found, and could not fix, a real, pre-existing vulnerability while wiring up the security job: `next@15.5.25` bundles its own internal `postcss@8.4.31` (four disclosed CVEs, patched at `>=8.5.23`), pinned as an exact internal dependency unrelated to our own `^8.4.47` devDependency (which already resolves to a patched version on its own — `pnpm audit` never flagged our own chain at all). Tried a `pnpm-workspace.yaml` override to force next's copy too; verified empirically (`require.resolve` from inside `next`, before and after a forced reinstall, an explicit `next>postcss` selector override, and confirming the lockfile was byte-identical with or without the override in place) that pnpm's override mechanism cannot reach a dependency a package requires internally at an exact pin — removed the override since it changed nothing either way, rather than ship dead configuration. See the technical debt ledger.

  Codex review: two P1s. (1) `pnpm audit --prod` skipped devDependencies entirely, so real vulnerable lint/test/build-tool dependencies would never be reported — and once `--prod` was removed, that's exactly what surfaced: `esbuild`, `vite` (×3), and a **critical**-severity `vitest` advisory (arbitrary file read/execute via its UI server), all pulled in transitively via `vitest ^2.1.2`/`@vitejs/plugin-react ^4.3.2`. Unlike the postcss/next case, these had a real, available fix — upgraded to `vitest ^5.0.0`/`@vitejs/plugin-react ^6.1.1` (forcing a fresh lockfile resolution, since `vite` isn't a direct dependency and pnpm won't bump a transitive peer on a plain reinstall), which pulled `vite` to 8.2.2 and closed all five. Re-ran the full frontend gate (lint, typecheck, 13 vitest tests, `next build`) after the major-version jump — all green; also fixed two harmless Vite 5 config-loader deprecation warnings the upgrade surfaced (`__dirname` → `import.meta.dirname`, added `"type": "module"`). (2) The postcss allowlist matched on `module_name != "postcss"` alone, which would have silently passed *any* future postcss advisory — a version bump, a different vulnerability, or postcss appearing via some other path — not just the four specific, already-investigated ones. Tightened to match the exact four advisory IDs *and* the exact dependency path (`next@15.5.25 > postcss@8.4.31`); anything else now fails. Verified both the pass path (current clean audit) and two distinct fail paths (an unrelated new advisory; the same advisory ID on a different path) by hand before wiring it into the workflow. Fixes: `827f7ae`. **Approved.**

  DB-lifecycle commands (upgrade/downgrade/upgrade/check against an empty DB) are unchanged from what Stage 3 already validated directly — not re-verified against a fresh disposable container here since Docker wasn't running in this environment and the local dev Postgres already has real data not worth a destructive re-test to prove something already proven. First real validation of the workflow's GitHub-Actions-specific mechanics (service container health checks, job-level `defaults.run.working-directory`, etc.) happens on the first actual push/PR.
- [x] Codex audit — conducted per-stage throughout Phase 1 (Stages 1–13), not as one end-of-phase pass; every stage above was independently reviewed and re-verified before the next began, per AGENTS.md's gate rule.
- [x] Resolve P0/P1 findings — every finding raised across all 13 stages was resolved and re-verified; none remain open. Codex's final word on Stage 13: "Phase 1 is feature-complete ... there are no remaining Codex P0/P1 blockers."

## Phase 2 — Projects + Tasks

Status: **Implementation plan approved (11 stages). Stages 1-3 complete.**
Stage 4 (Kanban board + drag reorder) is next. See the audit and decisions
below for the reasoning each stage builds
on.

Exit criteria: an ADMIN/OWNER can create a project and its tasks; any member
can see their own work, drag a task across a Kanban board, and get a 403/404
exactly where RBAC.md says they should; the dashboard's task/project tiles
show real counts instead of Stage 10's placeholders.

### Phase 0 audit: what's already specified

Unlike Phase 1, this phase needed no new architecture documents — Phase 0
(true Phase 0, before any product code existed) already specified the `work`
module in full, and nothing found in this audit requires changing it:

- **Schema** — [DATABASE.md §3](docs/architecture/DATABASE.md#3-tables) already
  has complete table definitions for `projects`, `project_members`,
  `milestones`, `tasks`, `task_comments`, `task_checklist_items`,
  `task_attachments`: every column, check constraint, index, and the
  `board_position numeric` fractional-indexing choice for drag-and-drop
  (already in the technical debt ledger below).
- **Cross-org integrity** — [DATABASE.md §5.1](docs/architecture/DATABASE.md#51-cross-organization-relationship-integrity)
  already specifies every person-reference column on these tables
  (`tasks.assignee_id`, `tasks.created_by`, `projects.owner_id`,
  `project_members.user_id`, `task_comments.author_id`) as a composite FK to
  `memberships (organization_id, user_id)`, not `users.id` — the exact pattern
  Phase 1's identity tables already implement, so nothing new to design, only
  to apply.
- **Deletion semantics** — [DATABASE.md §5.2](docs/architecture/DATABASE.md#52-membership-deletion-semantics)'s
  table already covers `tasks.assignee_id`/`projects.owner_id` (`RESTRICT`)
  and `project_members.user_id` (`CASCADE`).
- **Authorization** — [RBAC.md §2](docs/architecture/RBAC.md#2-permission-matrix)
  already has the role-level matrix rows (view/create/edit projects and
  tasks); [RBAC.md §3](docs/architecture/RBAC.md#3-enforcement) already
  specifies the resource-level predicates this phase implements in the
  service layer: task edit is `MANAGER+` **or** `task.assignee_id == user.id`
  **or** `task.created_by == user.id`; project detail is `MANAGER+` **or**
  membership in `project_members`; comment edit/delete is author-only
  (`ADMIN+` may delete); project-member management is gated at the route by
  a new `MEMBER`-tier permission and at the service by `MANAGER+` **or**
  `project.owner_id == user.id` (revised in RBAC.md §3 as part of this
  planning pass — decision 6 below). `core/authz/permissions.py`'s `Permission`
  enum already has every value this phase needs except one: `PROJECT_READ`,
  `TASK_READ`, `TASK_WRITE_OWN`, `TASK_WRITE_ANY`, `PROJECT_WRITE`,
  `PROJECT_DELETE` were built in Stage 6 and sit unused until now;
  `PROJECT_MEMBER_WRITE` is genuinely new, added by this planning pass'
  Codex round to close the route/service gap decision 6 describes.
- **Scope trims** — [ADR-0012](docs/adr/0012-v1-scope-trims.md) already
  defers a `TaskAssignee` join table (single `assignee_id` only) and stored
  `progress` (derived on read, per DATABASE.md §3). Not re-litigated.
- **One genuine gap, not an architecture gap — an unbuilt-infrastructure
  one**: [ADR-0008](docs/adr/0008-file-storage.md) (`FileStorage` protocol,
  `file_objects` table) is fully designed but was never built in Phase 1 —
  `organizations.logo_file_id` was deferred in Stage 1/3 for exactly this
  reason. Task attachments are the first real consumer, so this phase builds
  it for the first time, design already settled.

### Decisions made for Phase 2 (implementation-level, not architecture)

1. **Kanban reorder has no dedicated endpoint.** The client already holds the
   full column when dragging, so it computes the new `board_position` as the
   midpoint of the two neighbors and sends it as an ordinary field on the
   existing task-update route — the same pattern Stage 9's `PATCH
   /api/v1/memberships/{id}` already established (one resource, one PATCH,
   one guarded service call), not a new "/reorder" route. `ponytail: no
   server-side collision handling for two simultaneous drags on the same
   task; add optimistic-lock or a dedicated endpoint if that's ever observed
   in practice.`
2. **Activity events use the lowercase dotted style Phase 1 already
   established** (`task.created`, `task.status_changed`, `task.completed`,
   `project.created`, `project.status_changed`, `comment.created`), not
   MASTER_PROMPT §21's illustrative `SCREAMING_SNAKE_CASE` — matching
   `auth.session.created`, `membership.role_changed`, etc. These are ordinary
   business activity, `is_audit=false`, the first real feed content Phase 1
   built infrastructure for but never had data to populate.

   `project_member.added`/`project_member.removed` are **not** in that list —
   see [RBAC.md §3](docs/architecture/RBAC.md#3-enforcement)'s new resource
   rule (added alongside this planning pass): adding or removing a project
   member changes who can see the project, which is exactly guard 6's
   "permission-relevant ... change" (RBAC.md §5), so those two always record
   `is_audit=true` and get covered by an activity-writer-style test, the same
   pattern `test_activity_writer.py` already established in Stage 7 — not
   folded into the ordinary feed-event list above.
3. **Kanban board loads unpaginated but capped, not truly unlimited; every
   other list view follows ADR-0005's standard `{items, total}` +
   `limit`/`offset`.** A single project's task board is bounded by what one
   team works on at once — but "bounded in practice" isn't the same as
   "bounded by the API," so the board endpoint enforces a hard cap of 500
   tasks per project in one response (returned unordered-by-page, since a
   Kanban view can't sensibly paginate mid-column). `ponytail: 500 is a
   guess, not a measurement; if a real project ever approaches it, that's a
   virtualized-board or true-pagination problem to solve then, not a
   hypothetical one now` — logged in the technical debt ledger below.
   `GET /projects`, `GET /tasks` (cross-project, e.g. "My Work") paginate
   normally.
4. **Seed script gets two realistic projects, not MASTER_PROMPT §36's full
   list.** §36 also asks for 3–5 clients, which is a Phase 3/CRM concept —
   `projects.client_id` is nullable, so `scripts/seed.py` adds "TrinolIT
   Website" and an internal-product project (no client yet) with a spread of
   tasks across every status/priority, enough to exercise the Kanban board
   and dashboard tiles realistically without inventing CRM data this phase
   doesn't own. Full richness (client-linked projects, 20+ tasks, leads)
   completes once Phase 3 exists.
5. **"My Work" is the real `/tasks/my` frontend route MASTER_PROMPT §9
   specifies** (`/tasks`, `/tasks/my`, `/tasks/[id]` are page routes, not a
   query-string variant that replaces one of them), backed by the same
   backend task-list endpoint the plain `/tasks` page uses. The backend
   resolves "mine" from the caller's own session (`get_current_membership`),
   not a client-supplied sentinel like `assignee_id=me` — the endpoint's
   general `assignee_id` filter (useful on its own, e.g. a manager reviewing
   someone else's load) stays a real membership id, never a magic string.
   Stage 10's sidebar already has "My Work" as a disabled placeholder waiting
   for exactly this page.
6. **Project member management is `MANAGER+` or the project's own owner —
   route and service split, not a single check.** Formalized in
   [RBAC.md §3](docs/architecture/RBAC.md#3-enforcement) (revised alongside
   this planning pass) rather than left to ROADMAP.md alone, since it's a
   permanent authorization rule, not a one-off implementation note. Codex
   caught that the first version of this decision named only the
   service-level rule (`MANAGER+` **or** `project.owner_id == user.id`) and
   missed that `require(...)` runs *before* the service does: `PROJECT_WRITE`
   is `MANAGER+`-only, so a `MEMBER` who owns a project would be rejected by
   the route dependency before the service ever got to evaluate the
   ownership branch — the ownership half of the rule would have been dead
   code. Fixed the same way the codebase already solved this exact shape for
   tasks (`TASK_WRITE_OWN` vs `TASK_WRITE_ANY`): **one new `MEMBER`-tier
   permission**, `PROJECT_MEMBER_WRITE`, gates the route (everyone passes —
   it only controls *reaching* the service, per RBAC.md §2's new "Manage
   members of a project you own" row); the service then checks `actor.role`
   has `PROJECT_WRITE` (`MANAGER+`, §2's "Manage members of any project" —
   the same permission "create/edit projects" already uses, not a second new
   one) **or** `project.owner_id == user.id`. `role_on_project` is a closed
   enum (`LEAD | CONTRIBUTOR`) with **no permission weight of its own** —
   purely descriptive, so this doesn't introduce a second, project-scoped
   authorization dimension nothing in the spec asks for. Authz and isolation
   matrices explicitly cover both edge cases Codex named: a `MEMBER` who owns
   the project (must pass) and a `MEMBER` who doesn't (must 403).

### Checklist (11 implementation stages, per the approved stage plan)

- [x] Stage 1 — `work` module schema: `models.py` (Project, ProjectMember,
      Milestone, Task, TaskComment, TaskChecklistItem; `TaskAttachment`
      deferred to Stage 6 alongside `file_objects`) + migration `0003`;
      `PROJECT_MEMBER_WRITE` added to `Permission`/`_MEMBER` (decision 6).
      `alembic upgrade`/`downgrade -1`/`upgrade`/`check` all clean;
      schema-integrity and permission-hierarchy tests pass; full suite
      (160 tests), ruff, mypy all green. Entity-to-entity FK deletion
      semantics (not covered by DATABASE.md §5.2's person-column table)
      chosen and documented inline in `models.py`: `project_members.*` and
      `task_comments/task_checklist_items.task_id` CASCADE (child
      meaningless without parent, ADR-0011 confirms tasks/comments are hard
      -deleted); `tasks.milestone_id` RESTRICT (revised in review round 2
      below — `SET NULL` on a composite FK is unsafe here); `milestones.project_id` and
      `tasks.project_id` RESTRICT (projects are soft-deleted only per
      ADR-0011, so an unexpected hard delete should fail loudly, not
      cascade away real deliverable history). **Codex review round 1:** one
      P1, one P2, both fixed. P1 — `budget`, `estimated_hours`,
      `actual_hours`, `board_position` were annotated `Mapped[float]` over
      `sa.Numeric` columns, violating DATABASE.md §1/ADR-0007's "NUMERIC in
      Postgres, Decimal in Python, never float, anywhere in the stack" —
      applies beyond just money fields, since SQLAlchemy's `Numeric` type
      returns `Decimal` at runtime regardless, so the `float` annotations
      were already a latent type mismatch. Changed all four to
      `Mapped[Decimal]`. P2 — several composite FKs had no supporting
      index (DATABASE.md §1: "every FK has an index unless it is already
      the left prefix of a composite one"): added
      `ix_projects_org_owner`, `ix_milestones_org_project`,
      `ix_tasks_org_milestone`, `ix_tasks_org_created_by`; replaced the
      single `ix_project_members_organization_id` with
      `ix_project_members_org_project` + `ix_project_members_org_user`
      (neither existing composite FK was that index's prefix); widened
      `ix_task_comments_task`/`ix_task_checklist_items_task` to
      `(organization_id, task_id)` to match their FKs' own columns
      exactly. Migration `0003` edited in place (not a new migration) since
      nothing outside this local dev DB had applied it yet. Re-verified:
      `alembic downgrade -1`/`upgrade`/`check` clean, full suite
      (160 tests), ruff, mypy all green.

      **Codex review round 2:** one P1, one P2, both fixed. P1 —
      `fk_tasks_org_milestone_milestones` used `ON DELETE SET NULL`, but
      it's a **composite** FK (`organization_id`, `milestone_id`); Postgres
      nulls every referencing column on that cascade action, not just the
      one that "should" go null — here that includes `organization_id`,
      which is `NOT NULL` on `tasks`. Deleting a milestone with linked
      tasks would have raised a NOT NULL violation instead of gracefully
      unlinking them. Changed to `ON DELETE RESTRICT` (fail loudly; the
      service unlinks tasks explicitly before deleting a milestone that
      still has them) — same fix shape as `milestones`/`tasks` →
      `projects` above. This is a general composite-FK hazard, not
      specific to this table: found and fixed the identical bug already
      sitting in DATABASE.md §3's own spec for
      `organizations.logo_file_id` → `file_objects` (`ON DELETE SET NULL`
      on `(id, logo_file_id)` would try to null `organizations.id`, a
      primary key) before Stage 6 could inherit it — see DATABASE.md §3
      and this checklist's Stage 6 entry above, both corrected. P2 — two
      more FKs still lacked matching indexes: added
      `ix_task_comments_org_author` (`fk_task_comments_org_author_memberships`
      had none) and `ix_tasks_org_project` (the DATABASE.md §3-mandated
      `ix_tasks_project (project_id)` doesn't itself satisfy
      `fk_tasks_org_project_projects`'s `(organization_id, project_id)`
      shape — kept the spec-mandated index as-is, added the composite one
      alongside it). Re-verified: `alembic downgrade -1`/`upgrade`/`check`
      clean, full suite, ruff, mypy all green.
- [x] Stage 2 — Project CRUD + `project_members` management (decision 6
      above: route gated on the new `PROJECT_MEMBER_WRITE` permission,
      MEMBER-tier; service enforces `PROJECT_WRITE` (MANAGER+) OR
      `project.owner_id == user.id`; `role_on_project` is
      `LEAD | CONTRIBUTOR`, no permission weight). `modules/work/{schemas,
      services/project_service,services/project_member_service,
      routes/projects}.py`. Two implementation-level decisions not
      previously spelled out: **(a)** `create_project` always adds the
      owner to `project_members` as `LEAD`, so "membership in
      `project_members`" is the single, uniform visibility check RBAC.md
      §3's "Project detail" rule needs — no separate `owner_id` branch:
      removing the owner from the roster is rejected (409) to keep that
      invariant intact, ownership transfer isn't implemented (not
      requested). **(b)** `GET /projects` (list) applies the same
      visibility rule as project detail, filtering to a MEMBER's own
      projects — otherwise list responses would leak fields the detail
      route would 403 on. Also excludes archived projects (ADR-0011). The
      authz-matrix meta-assertion (Phase 1 Stage 11) required handling now,
      not deferred to Stage 9: `GET/POST/PATCH/DELETE` on
      `/projects/{id}/members` and `GET /projects/{id}` are route/service-
      split routes (PROJECT_MEMBER_WRITE and PROJECT_READ are both
      MEMBER-tier at the route; the real rule is ownership/membership,
      enforced in the service) — the generic per-row assertion doesn't fit
      that shape, so these routes are tracked in a separate
      `_OWNERSHIP_SPLIT_ROUTES` set (satisfies the meta-assertion honestly)
      with the real behavior asserted by dedicated tests in
      `test_projects.py`/`test_project_members.py`, covering all four
      decision-6 cases. `apps/web/lib/api/types.gen.ts` regenerated (`make
      openapi`), no diff drift. **Codex review:** all four P1s and one P2
      fixed. Concurrent duplicate creates now catch the unique violation
      from `flush()` and return 409; PATCH rejects null required fields,
      validates dates against the stored counterpart, and only translates
      `uq_project_org_code`; budget input is a bounded decimal string in
      both validation and generated OpenAPI; every project-member route has
      manager, MEMBER-owner, MEMBER-non-owner, and cross-org matrix cases;
      trigger-generated `updated_at` values are mapped and reloaded after
      update/archive. Full suite (245 tests), ruff, mypy, frontend
      lint/typecheck/test/build all green.
- [x] Stage 3 — Task CRUD, status/priority transitions, milestone linking.
      `modules/work/{services/task_service,services/milestone_service,
      routes/tasks}.py` + milestone routes added to `routes/projects.py`
      (`POST/GET /projects/{id}/milestones`). Proactively applied the same
      trigger-`updated_at`/`FetchedValue` fix Codex's Stage 2 review found
      on `Project` to `Task`/`TaskComment` too, before their own update
      paths could hit the identical bug.

      Implementation-level decisions, since RBAC.md documents "Task edit"
      but not every case this stage needed:
      1. **Task read is org-wide, with no per-resource restriction** —
         unlike "Project detail," RBAC.md §3 has no "Task detail" bullet,
         only "Task edit." Read is transparency (same as Team's own "view"
         row); only editing is ownership-restricted. Flagged explicitly for
         review since the asymmetry with projects isn't spelled out.
      2. **Task delete follows the same rule as task edit** (`MANAGER+` OR
         assignee OR creator) — RBAC.md's matrix has no dedicated
         task-delete permission, and ADR-0011 treats deleting a task as a
         normal, audited action, not one confined to managers. Inventing a
         new `TASK_DELETE` permission not in the accepted enum would have
         been scope creep; reusing the existing edit rule wasn't.
      3. **`completed_at` is never client-settable** — derived entirely
         from `status` (set on transition to `DONE`, cleared otherwise),
         removed from both create/update request schemas. One source of
         truth for `ck_task_completed` instead of trusting a client-sent
         date to agree with the status sent alongside it.
      4. **Milestones follow "Create/edit projects" (`MANAGER+`), not
         decision 6's ownership exception** — that exception is documented
         in RBAC.md §3 only for `project_members` specifically; milestones
         are structural project data, closer to editing the project's own
         fields (also `MANAGER+`-only, no ownership escape hatch).
      5. **`board_position` is deliberately absent from the task
         create/update schemas** — it's Stage 4's field to expose, once the
         Kanban drag-reorder feature that gives it meaning actually exists.
      6. Money/hours decimal-string validation (Codex's Stage 2
         `BudgetDecimal` fix) generalized to a shared `_validate_decimal_string`
         helper + a new `HoursDecimal` (non-negative, `Numeric(6,2)`) for
         `estimated_hours`/`actual_hours` — each alias stays a literal
         `Annotated[...]` assignment (not a factory-function call), since
         mypy only recognizes an implicit type alias in that exact shape.

      Route/service-split routes (same shape as decision 6, RBAC.md §3):
      `GET /projects/{id}/milestones` (visibility) and
      `PATCH`/`DELETE /tasks/{id}` (edit/delete) join
      `_OWNERSHIP_SPLIT_ROUTES` in the authz matrix, each with a dedicated
      4-or-5-way test covering every case (manager, assignee, creator,
      unrelated member, cross-org), mirroring the pattern Codex's Stage 2
      review established for project members.

      `apps/web/lib/api/types.gen.ts` regenerated, no drift. Full suite
      (302 tests), ruff, mypy, frontend lint/typecheck/test/build all
      green.
- [ ] Stage 4 — Kanban: board endpoint (500-task cap, decision 3), drag
      reorder via the existing task `PATCH` (decision 1)
- [ ] Stage 5 — Task comments + checklist items
- [ ] Stage 6 — `platform.FileObject` + `FileStorage` protocol: **both**
      `LocalFileStorage` and `S3FileStorage` — ADR-0008 decided both ("one
      interface, two implementations, no speculative third"), and
      MASTER_PROMPT §24 requires S3-compatible storage in production
      specifically; "S3 if time allows" would silently trim an
      already-accepted requirement, not defer an undecided one. **New
      infrastructure, not a reuse**: `file_objects` doesn't exist in any
      migration yet (`organizations.logo_file_id` was deferred in Stage 1/3
      for exactly this reason). `TaskAttachment` + migration `0004` land
      here, once `file_objects` exists. **`organizations.logo_file_id` and
      its composite FK are restored in this same migration** — Codex caught
      that the first pass of this stage only wired `task_attachments`,
      leaving the logo relationship still deferred even though its
      prerequisite (`file_objects`) now exists in the same migration that
      would add it. `Organization.logo_file_id: uuid.UUID | None` +
      `FOREIGN KEY (id, logo_file_id) REFERENCES file_objects
      (organization_id, id) ON DELETE RESTRICT` (DATABASE.md §3/§5.1 —
      `organizations` uses its own `id` as the tenant key here, not an
      `organization_id` column, since it's the tenant root; `RESTRICT`, not
      `SET NULL`, because a composite FK's `SET NULL` nulls every
      referencing column including `id`, the primary key — corrected in
      DATABASE.md §3 itself during Stage 1 review after Codex caught the
      identical bug shape on `tasks.milestone_id`). Needs a dedicated
      regression check, not just the generic schema-integrity test: that
      test walks `information_schema` for org-scoped tables identified by
      an `organization_id` column, and `organizations` itself has none — so
      a single-column-FK regression here wouldn't be caught by the existing
      generic assertion the way it would for any other table.
- [ ] Stage 7 — Activity feed events wired for task/project changes
      (decision 2 above); first real exercise of `platform.activity.
      list_feed` (built Stage 7 of Phase 1, never called by a route until
      now). `project_member.added`/`removed` write `is_audit=true` instead
      (decision 2 above, RBAC.md §3) — covered by an activity-writer-style
      test, not the feed test.
- [ ] Stage 8 — Frontend: Projects list/detail, Tasks list/detail, Kanban
      board (drag-and-drop UI for decision 1), `/tasks/my` page + backend
      support (decision 5 above — a real route, not a query-param
      substitute), dashboard tiles replacing Stage 10's "Open tasks"/"Active
      projects" placeholders with real counts, "My Work" nav enabled
- [ ] Stage 9 — Security matrices extended: the authz-matrix meta-assertion
      (Phase 1 Stage 11) already fails the suite if any new Project/Task
      route has no row, so this is enforced structurally, not by discipline
      alone. Explicitly includes project-member-management rows (decision 6)
      covering all four cases: `MANAGER`/`ADMIN`/`OWNER` (allowed via role),
      a `MEMBER` who owns the project (allowed via ownership — the case a
      route-only check would have missed), a `MEMBER` who doesn't own it
      (403), and the isolation-matrix row (org B's member, owner or not,
      against org A's project — 404).
- [ ] Stage 10 — `scripts/seed.py` extended (decision 4 above)
- [ ] Stage 11 — E2E foundation (Playwright) — first real page with content
      to click through; TESTING.md §5 already scopes this to
      main/release-candidate runs, not every PR
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
| Kanban drag reorder has no collision handling for two simultaneous drags on the same task | Phase 2 plan, ROADMAP.md decision 1 | observed in practice; add optimistic locking or a dedicated reorder endpoint |
| Kanban board endpoint caps at 500 tasks per project, unpaginated, in one response — a guessed ceiling, not a measured one | Phase 2 plan, ROADMAP.md decision 3 | a real project approaches the cap; add a virtualized board or true pagination |
| Single activity table | ADR-0006 | ~50M rows; partition by month |
| Proxied uploads | ADR-0008 | files over ~25 MiB or API host saturates |
| App-layer org scoping, not RLS | ADR-0003 | V4 multi-tenant SaaS |
| Session revocation reconciled on exchange + daily sweep | AUTH.md §8 | near-instant revocation needed |
| minio omitted from Phase 1 Compose | Stage 1 plan (`docs/adr/0001-monorepo-and-stack.md`'s sibling decisions) | whichever phase first adds file uploads (task attachments, Phase 2) |
| Org-scope guard covers select/update/delete, not bulk Core `insert()` | `core/db/org_session.py` | a bulk insert is ever written instead of `session.add()`/`OrgSession.add()` |
| Contact-endpoint origin exception is a single hardcoded special case, not a general allowlist | `core/security/origin_check.py` | a second endpoint ever needs a non-default origin |
| No membership reactivation path — a former (INACTIVE/ON_LEAVE) member can't be brought back except directly in the DB; invitation_service now deliberately refuses to re-invite them instead of creating a dead invitation | `invitation_service.create_invitation` | Team endpoints (Stage 9) or whichever stage needs to let an ADMIN reactivate someone |
| Auth rejections with no determinable organization are logged, not audited | `session_service.py` (AUTH.md §5) | never — `activity_events.organization_id` is NOT NULL by design; would need a schema change (a nullable org column, or a separate unattributed-events table) to close |
| Codex's Stage 9 re-review flagged a "CI documentation mismatch" (P2, nonblocking) without the specific text reaching this log — needs the exact finding before it can be fixed rather than guessed at | TESTING.md §6 / Makefile `check` target, most likely | next Codex round that restates it, or before Stage 13 builds CI for real |
| No `/team/[id]` member detail page — the plan's route list names it, but nothing in Phase 1 needs more than the list view yet | `app/(app)/team/` | whichever stage first needs a per-member detail view (editing job title, viewing their activity) |
| Team page fetches only the first 50 members and has no pager UI, even though the API already returns `total` for exactly this | `app/(app)/team/page.tsx` | an org with >50 members shows up in testing/seed data, or Stage 11+ adds a pagination component other lists can share |
| Team empty state has no "Invite someone" action — it's copy only, `POST /api/v1/invitations` isn't wired to any button yet | `components/list/empty-state.tsx` usage in `app/(app)/team/page.tsx` | whichever stage builds the invite-a-member UI (a modal/form calling the Stage 8 endpoint) |
| CSRF token is in-memory only (`lib/api/client.ts`) and isn't rehydrated after a hard page reload until the next `GET /auth/session` call — any unsafe request issued before that will 403 | `lib/api/client.ts`'s `csrfToken` module state | a page that needs to fire a mutation immediately on load without an intervening session-info fetch first |
| `next@15.5.25` bundles its own internal `postcss@8.4.31` (four disclosed CVEs, patched at `>=8.5.23`) — verified empirically that a pnpm override can't reach it (it's an exact pin next requires internally), so no package.json-level fix exists. CI's `pnpm audit` step allowlists specifically this (`module_name == "postcss"`), failing hard on anything else | `.github/workflows/ci.yml`'s security job | a next.js release bumps its internal postcss pin past 8.5.23, or the project adopts pnpm's `patchedDependencies` to force-patch next's own `package.json` |

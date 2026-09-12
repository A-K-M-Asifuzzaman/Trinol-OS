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

Status: **APPROVED by Codex.** All 11 stages complete and independently
reviewed; the final Phase 2 audit found no P0/P1/P2 findings.

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

      **Codex review:** two P1s, both fixed. P1 — `delete_task` hard-
      deleted and committed with no activity event, despite ADR-0011's
      "Deleting a task... really deletes it. The audit event keeps the
      record of who did it and when" — after a hard delete the row is
      gone, so unlike ordinary task lifecycle events (correctly deferred
      to Stage 7), this one event can't be added retroactively. Now calls
      `platform.activity.record(..., audit=True)` (`task.deleted`) in the
      same transaction as the delete, with a test asserting exactly one
      such row via `list_audit`. P1 — `TaskUpdateRequest.project_id` had a
      runtime/OpenAPI mismatch: it genuinely accepts an explicit `null` to
      unproject a task (like `assignee_id`/`milestone_id`), but a copy-
      pasted `WithJsonSchema` override (meant for `title`/`status`/
      `priority`, which really do reject null) hid that from the generated
      schema, so `types.gen.ts` declared `project_id?: string` instead of
      `string | null`. Removed the override; regenerated types now show
      `project_id?: string | null` correctly, with a test covering the
      clear-to-null round trip. Re-verified: full suite (304 tests), ruff,
      mypy, frontend lint/typecheck/test/build, OpenAPI diff all green.
- [x] Stage 4 — Kanban: board endpoint (500-task cap, decision 3), drag
      reorder via the existing task `PATCH` (decision 1).
      `modules/work/services/board_service.py` +
      `GET /projects/{id}/board` on `routes/projects.py`. Groups a
      project's tasks by status (`{columns, total, truncated}`), capped at
      500 tasks ordered by `board_position`, ascending, tie-broken by `id`
      — `truncated` tells the caller honestly whether the cap actually
      excluded anything, rather than silently returning a partial board
      with no signal. Route/service-split, same shape as "Project detail"
      (`PROJECT_READ` route, `ensure_project_visible` service) — folded
      into the existing milestone-visibility matrix test
      (`test_project_subresource_reads_enforce_project_visibility`,
      parametrized over both routes, since they share the identical rule)
      rather than duplicating it.

      `board_position` added to `TaskUpdateRequest` — no dedicated reorder
      endpoint (decision 1); a new `BoardPositionDecimal` schema type
      accepts any syntactically valid, finite decimal string (rejects
      `NaN`/`Infinity`/non-numeric input with a 422) and, unlike
      `Budget`/`HoursDecimal`, applies no digit-count bound, since the
      column itself (`sa.Numeric`, no declared precision/scale) is
      genuinely unbounded — fractional-indexing midpoints over many
      reorders can need arbitrary precision. `board_position` is `NOT
      NULL`, so it joins `title`/`status`/`priority` in
      `_required_fields_not_null` (with the matching `WithJsonSchema`
      override that correctly hides `null`, this time for a field that
      really does reject it — see Stage 3's `project_id` fix for the
      opposite mistake). Renamed `routes/tasks.py`'s `_task_to_response`
      to public `task_to_response` so the board route (in
      `routes/projects.py`) can reuse it rather than duplicating the
      mapping.

      Both technical-debt-ledger rows for this stage (drag-reorder
      collision handling; the 500-task cap being a guessed ceiling) were
      already logged during Phase 2 planning — nothing new to add.

      `apps/web/lib/api/types.gen.ts` regenerated, no drift. Full suite
      (320 tests), ruff, mypy, frontend lint/typecheck/test/build all
      green.
- [x] Stage 5 — Task comments + checklist items.
      `modules/work/services/{task_comment_service,task_checklist_service}.py`
      + routes nested under `/tasks/{id}/comments` and
      `/tasks/{id}/checklist-items` (`routes/tasks.py`). Applied ADR-0011's
      audit-on-delete requirement correctly from the start this time
      (`task_comment.deleted`/`task_checklist_item.deleted`,
      `is_audit=true`) — it names comments and checklist items
      explicitly alongside tasks, the exact gap a prior Stage 3 review
      round caught for `delete_task`.

      Two implementation-level decisions, since RBAC.md documents comment
      edit/delete but nothing about creation or checklist items:
      1. **Comment creation is open to every role**, no restriction beyond
         being able to see the task (org-wide, Stage 3 decision) — same
         reasoning as task creation's own "everyone" rule. RBAC.md §3 only
         restricts edit/delete, not creation.
      2. **Checklist items follow the task-edit rule (`can_write_task`:
         `MANAGER+` or assignee or creator), not comments' author-only
         rule** — a checklist item has no `author_id` column at all
         (DATABASE.md §3), so there's no identity to hang an author-only
         rule on; it's task content, not independent discourse, and
         inherits the parent task's own write permission instead.

      RBAC.md §3's exact asymmetry implemented precisely: comment **edit**
      is author-only with **no** `ADMIN+` override at all (unlike task
      edit's `MANAGER+` escape hatch), while comment **delete** does allow
      `ADMIN+` — a dedicated test (`test_comment_routes_enforce_author_
      only_edit_admin_delete`) covers exactly the case where these two
      diverge (an ADMIN who isn't the author: 403 on PATCH, 204 on
      DELETE). `edited_at` is derived server-side on every body change,
      mirroring `completed_at`'s Stage 3 pattern — never client-settable.

      Comment/checklist-item write routes are further split-permission
      cases (route: `TASK_WRITE_OWN`, MEMBER-tier; service: the real
      rule), joining `_OWNERSHIP_SPLIT_ROUTES` with dedicated multi-way
      tests, same pattern as every prior stage's split routes.

      `apps/web/lib/api/types.gen.ts` regenerated, no drift. Full suite
      (373 tests), ruff, mypy, frontend lint/typecheck/test/build all
      green.
- [x] Stage 6 — `platform.FileObject` + `FileStorage` protocol: **both**
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

      **Implementation.** `platform/file_storage/{protocol,local,s3,deps}.py`
      (not `platform/storage/` — that name collides with `.gitignore`'s
      `storage/` pattern, which matches at *any* depth, not just repo
      root; caught before committing by noticing the package was silently
      absent from `git status`, not by design — renamed rather than
      touching the gitignore rule, which is correctly scoped to the
      runtime upload directory) —
      `FileStorage` (`put`/`get`/`delete`/`exists`), `LocalFileStorage`
      (plain directory, `asyncio.to_thread`-wrapped), `S3FileStorage`
      (`boto3`, also `to_thread`-wrapped since it's a sync client), and
      `get_file_storage()` selected by `STORAGE_BACKEND` (same DI-override
      pattern as `get_email_sender`/`get_identity_verifier`). `platform/
      files.py`'s `create_file_object()` does upload validation
      (SECURITY.md §6: 10 MiB cap, extension allowlist, sniffed content
      type via magic-byte signatures — PNG/JPEG/WebP/PDF only, SVG
      rejected by the same general mechanism, no special case) and writes
      the `file_objects` row; doesn't commit, so the caller (`task_
      attachment_service.create_attachment`) adds `TaskAttachment` in the
      same transaction. Upload is multipart (`UploadFile`); download
      streams with `Content-Disposition: attachment` and
      `X-Content-Type-Options: nosniff`, authorized by the parent task's
      own read rule (org-wide, Stage 3) — no separate attachment
      permission, per ADR-0008. `TaskAttachment`'s write routes
      (upload/delete) follow `can_write_task`, same as checklist items —
      task content, no author concept. Deletion writes a `task_attachment.
      deleted` audit event and removes both the `file_objects` row and the
      blob (commit before the blob delete, so a failure after orphans a
      blob — the documented backstop — rather than leaving a dangling DB
      reference to an already-deleted one). Proactively applied the same
      trigger-`updated_at`/`FetchedValue` fix to `Organization` while its
      model was open for `logo_file_id` anyway, even though no route
      updates it yet — closing the gap before a future org-settings
      feature could independently rediscover it, same reasoning as
      Stage 3's `Task`/`TaskComment` fix.

      **Major finding, unrelated to this stage's own feature work:** while
      writing this stage's dedicated `organizations.logo_file_id`
      regression test, discovered that `tests/security/
      test_schema_integrity.py`'s two composite-FK checks
      (`_foreign_keys()`, added Phase 1 Stage 3) have returned **zero
      rows** to every test run since they were written — `information_
      schema.constraint_column_usage`'s own definition only shows rows to
      a role with `pg_has_role(table_owner, 'USAGE')`, and `trinol_app`
      (the role the whole suite and CI run as) is deliberately not a
      member of `trinol_migrator` (ADR-0006's two-role split). Both
      assertions have therefore been vacuously true for the entire
      project's history — a schema-safety CI gate that never actually
      checked anything. Rewritten to query `pg_constraint`/`pg_attribute`/
      `pg_class` directly (no owner-role restriction), which also fixed a
      second, independent bug the same rewrite exposed: the old query's
      join produced a cross product across both sides' columns before
      `array_agg`, silently duplicating entries for any multi-column FK —
      invisible before only because every prior assertion happened to be
      duplication-insensitive (`set()`-wrapped or presence/length checks),
      unlike this stage's new positive-existence assertion. **Verified
      empirically, not just reasoned about:** confirmed via direct `psql`
      queries as `trinol_app` that the old query returned 0 rows and the
      new one doesn't; confirmed the fixed test now genuinely rejects a
      deliberately-added single-column FK between two real org-scoped
      tables (`tasks` → `projects`), then removed it — matching Stage 3's
      own historical verification discipline for this exact test file.
      See CHANGELOG.md for the condensed version.

      Full suite (415 tests, including new `test_local_file_storage.py`
      and mocked-boto3 `test_s3_file_storage.py`), ruff, mypy,
      `alembic upgrade`/`downgrade -1`/`upgrade`/`check` clean, frontend
      lint/typecheck/test/build, OpenAPI diff all green.

      **Codex review:** two P1s, both fixed. P1 — Content-Disposition
      header injection: `download_attachment_route` interpolated the
      user-supplied upload `filename` directly into a quoted header value
      with no sanitization; a filename containing `"` could close the
      quoted string early and append arbitrary header content, and a raw
      CR/LF byte could inject an entirely new header line (e.g.
      `Set-Cookie`). Added `_content_disposition()`: an RFC 6266
      `filename*` value percent-encodes the *whole* name
      (`quote(..., safe="")` leaves no raw quote/backslash/control byte
      anywhere in it), with an ASCII `filename=` fallback built by
      substituting (not deleting) any character outside
      `[A-Za-z0-9 ._-]`, so the fallback can never end with a dangling
      escape and is never empty for non-empty input. 7 dedicated unit
      tests exercise the helper directly with quotes, backslashes,
      embedded CRLF, non-ASCII, and empty input.

      P1 — task deletion orphaned attachment files: `task_attachments`
      cascades away at the DB level when a task is hard-deleted
      (Stage 1), but `file_objects` doesn't hang off `tasks` in the FK
      graph at all — `delete_task` never touched it, so every task
      delete that had attachments silently orphaned both the metadata row
      and the real storage blob. Not a rare edge case: the *only* path by
      which this could happen, and my own first-pass test for this
      (`test_deleting_task_cascades_attachment_rows`) only checked that
      the task 404'd afterward, never checking whether the attachment's
      `file_objects` row or blob were actually gone — the gap went
      untested, not just unfixed. `delete_task` now takes a `FileStorage`
      parameter and explicitly deletes, in FK-dependency order
      (`task_attachments` → `file_objects` → `tasks`, since
      `file_objects`'s `RESTRICT` would otherwise reject a still-
      referenced row): the attachment rows, then the file_objects rows,
      then the task itself, commits, then deletes each blob — same
      commit-before-blob-delete ordering `delete_attachment` already
      established. Renamed and strengthened the test
      (`test_deleting_task_cleans_up_attachment_rows_and_blobs`) to assert
      directly against the database and the filesystem that both are
      actually gone, not just that the task itself 404s.

      Re-verified: full suite (422 tests), ruff, mypy, `alembic check`
      clean, frontend lint/typecheck/test/build, OpenAPI diff all green.
- [x] Stage 7 — Activity feed events wired for task/project changes
      (decision 2 above); first real exercise of `platform.activity.
      list_feed` (built Stage 7 of Phase 1, never called by a route until
      now). `project_member.added`/`removed` write `is_audit=true` instead
      (decision 2 above, RBAC.md §3) — covered by an activity-writer-style
      test, not the feed test.

      **Implementation.** `record()` calls added inside each service's
      existing transaction (never a separate commit, per ADR-0006):
      `create_project`/`update_project` write `project.created` and, only
      when `status` is actually among the changed fields and differs from
      the prior value, `project.status_changed` (`{"from", "to"}`
      metadata) — an unrelated field update writes nothing. `create_task`
      writes `task.created`; `update_task` writes `task.completed`
      (`{"from"}` metadata) when a status change lands on `DONE`, else
      `task.status_changed` (`{"from", "to"}`) for any other status
      change, and nothing for a non-status update — same conditional
      pattern as projects. `create_comment` writes `comment.created`.
      `add_project_member`/`remove_project_member` write `project_member.
      added`/`removed` with `audit=True`, unchanged from decision 2's
      original reasoning (a project-membership change is
      permission-relevant, not feed content — RBAC.md §3 guard 6).

      New `platform/routes/activity.py`: `GET /api/v1/activity`, the first
      route either `list_feed` or the new `count_feed()` (added
      alongside it — `list_feed`/`list_audit`'s own signatures are
      untouched, to avoid touching Phase 1's `test_activity_writer.py`)
      has ever had. Org-wide, not project-nested — `list_feed` takes no
      project filter, and MASTER_PROMPT §21 lists "Recent activity" as a
      **Dashboard** widget, not a project-detail one. Gated by
      `Permission.PROJECT_READ` (reused, not invented): the closest
      existing MEMBER-tier "work visibility" permission, matching this
      route's org-wide-transparency shape (same as `GET /api/v1/tasks`).
      `platform/schemas.py` (new file): `ActivityEventResponse`/
      `ActivityFeedResponse` (`{items, total}`, ADR-0005) — Pydantic's
      `BaseModel` does **not** reserve the field name `metadata` (unlike
      SQLAlchemy's `DeclarativeBase`, which does — the reason the ORM
      column is `event_metadata`/`"metadata"` in the first place);
      confirmed both by mypy and by the route's own tests actually
      exercising response serialization, not assumed.

      **Verification snag, not a review finding:** two pre-existing
      `test_projects.py` tests (`test_concurrent_duplicate_project_code_
      only_one_succeeds`, `test_update_and_archive_return_trigger_
      refreshed_updated_at`) run outside the per-test rollback wrapper —
      real cross-connection commits, needed to exercise genuine DB-level
      concurrency — and hand-clean their own rows afterward, including a
      `DELETE FROM organizations`. Once `create_project`/`update_project`
      started writing activity_events rows, that delete started failing:
      `activity_events.organization_id` is `ON DELETE RESTRICT` (Phase 1
      migration 0001, ADR-0006's append-only guarantee), and — the actual
      blocker — `trinol_app` has `UPDATE`/`DELETE` revoked on
      `activity_events` entirely, so even deleting the activity_events
      rows first isn't an option available to the app role the test suite
      runs as. Fixed by no longer attempting to delete the `Organization`
      row in either test's cleanup (each test uses a fresh `uuid7` org id,
      so the orphaned row causes no collision on rerun) — a documented,
      deliberate gap, not a workaround for a bug.

      Added 16 new tests (422 → 438): 8 activity-writer-style tests in
      `test_activity_writer.py` (one per event above, plus the
      no-status-change-writes-nothing negative case for both projects and
      tasks, plus the project-member add/remove/audit-only/not-in-feed
      case decision 2 calls for), a new `test_activity_feed.py` (3 tests:
      items+total shape, project_member events excluded from the feed,
      org isolation), and the new authz-matrix row's 4-role parametrized
      expansion (`× list(Role)`, same as every other row). Multi-event
      assertions compare by event-name
      set/dict rather than list order — `created_at`'s `server_default
      text("now()")` is Postgres transaction time, not statement time, so
      two `record()` calls inside one test's single transaction can tie
      on it; list order on a tie isn't guaranteed by
      `ORDER BY created_at DESC` alone. Added a new `test_authz_matrix.py`
      row for `GET /api/v1/activity` (`PROJECT_READ`, org-wide, no
      ownership split — same shape as the task-read rows already there).

      Full suite (438 tests, was 422 going into this stage), ruff, mypy,
      frontend lint/typecheck/test/build, OpenAPI diff all green.
- [x] Stage 8 — Frontend: Projects list/detail, Tasks list/detail, Kanban
      board (drag-and-drop UI for decision 1), `/tasks/my` page + backend
      support (decision 5 above — a real route, not a query-param
      substitute), dashboard tiles replacing Stage 10's "Open tasks"/"Active
      projects" placeholders with real counts, "My Work" nav enabled

      **Implementation.** No backend changes — every endpoint this stage
      needs already existed (Stages 2–7). `lib/api/client.ts` gained
      `Project`/`Task`/`ProjectBoard` types and
      `fetch*`/`create*`/`update*`/`deleteTask` wrappers, same shape as
      the existing `fetchTeamMembers`. `app/(app)/projects/page.tsx` and
      `app/(app)/tasks/page.tsx` follow Team's established client-
      rendered/four-state pattern (Stage 10) with an inline create form
      (react-hook-form + zod, same as the login page); `/tasks` page
      passes `showCreateForm`, `/tasks/my` doesn't. `app/(app)/tasks/
      my/page.tsx` is a **server** component — it resolves the caller's
      own `user_id` from `fetchSessionInfo` server-side (decision 5: never
      a client-supplied `assignee_id=me` sentinel) and passes it into the
      shared `components/tasks/task-list.tsx` client component, which
      both `/tasks` and `/tasks/my` render.

      `components/board/kanban-board.tsx`: native HTML5 drag-and-drop
      (`draggable`/`onDragStart`/`onDragOver`/`onDrop`) — no new
      dependency (`dnd-kit` etc.), the ladder's "native platform feature"
      rung covers it. Dropping a card computes `board_position` as the
      midpoint of its new neighbors' positions (decision 1: reuses the
      existing `PATCH /tasks/{id}`, no dedicated reorder endpoint) —
      dropping before a specific card, not just appending to the column,
      so an actual mid-column reorder is possible, not merely a move
      between columns. `ponytail: plain float arithmetic for the
      midpoint, not arbitrary-precision — repeated drops onto the exact
      same slot will eventually run out of representable midpoints;
      already covered by the technical debt ledger's existing "no
      collision handling" entry for Kanban reorder, not a new gap`.
      `app/(app)/projects/[id]/page.tsx` fetches the project and its
      board, renders `KanbanBoard`, and invalidates the board query on
      every successful move (a refetch, not optimistic cache patching —
      simplest correct option, revisit only if the refetch lag is ever
      actually reported as a problem).

      Dashboard tiles: `Open tasks`/`Active projects` now show real
      `fetchTasks`/`fetchProjects` totals rather than Stage 10's
      placeholders. `ponytail: both are *total* counts, not "open"/
      "active" filtered ones — GET /projects has no status filter and GET
      /tasks only supports one equality filter, so a true filtered count
      needs either a dedicated count endpoint or several requests; add
      when a real report needs it, MASTER_PROMPT §21's "Recent activity"
      widget (Stage 7) is the richer version of this dashboard need
      already built`. Sidebar's "My Work"/"Projects"/"Tasks" now link to
      real routes instead of rendering as disabled labels.

      New tests: `tests/projects.test.tsx` (four states, MSW-backed, same
      pattern as `tests/team.test.tsx`) and `tests/kanban-board.test.tsx`
      (drag interaction — drop into an empty column computes position
      `"0"`; drop before an existing card computes the correct midpoint,
      asserted directly against `onMoveTask`'s call arguments, not the
      DOM). 19 frontend tests passing (was 13).

      **Manual verification, partial.** Backend server + web dev server
      both started locally against the real local Postgres (no Docker in
      this environment, same as every prior stage's DB-lifecycle
      checks) and every new route (`/projects`, `/projects/[id]`,
      `/tasks`, `/tasks/[id]`, `/tasks/my`, `/dashboard`) confirmed to
      render server-side with no crash — `/tasks/my`'s no-session
      fallback (`fetchSessionInfo` failing, caught, rendering the
      documented error state) verified directly, not merely inspected in
      source. **Could not** complete an actual authenticated
      click-through (create a project/task, drag a card, watch the
      dashboard tile update) — `FIREBASE_CREDENTIALS` is unset in this
      environment (same pre-existing gap Phase 1's own blocked-items list
      already documents; no stage before this one has had a real
      authenticated browser session available either), and Chromium isn't
      installed for Playwright here. Full click-through coverage is
      Stage 11's Playwright smoke spec, which runs against a real dev
      stack outside this constraint. Ruff/mypy/pytest untouched (no
      backend files changed this stage); OpenAPI diff clean; ESLint,
      `tsc --noEmit`, Vitest, and `next build` all green.

      **Codex review: two non-blocking P2s, both fixed.** (1) A failed
      Kanban move (`updateTask` rejecting) was silently swallowed — no
      revert, no message, the user would see nothing happen and no
      indication why. `ProjectDetailPage` now wraps the move in
      `try`/`catch` and renders the `ApiError` message as a `role="alert"`
      banner (same pattern as the task-detail page's own action errors);
      a new `tests/project-detail.test.tsx` drives a real drag/drop
      through a mocked failing `PATCH /tasks/{id}` and asserts the banner
      appears. (2) The dashboard's "Open tasks"/"Active projects" labels
      implied status-filtered counts when the values were always totals
      — relabeled to "Total tasks"/"Total projects" rather than building
      the status-aware query path (MASTER_PROMPT doesn't mandate these
      exact labels; a real filtered count is still the documented
      `ponytail:` follow-up if a report ever needs one). 20 frontend
      tests passing (was 19); ESLint, `tsc --noEmit`, Vitest, `next
      build` re-verified green.
- [x] Stage 9 — Security matrices extended: the authz-matrix meta-assertion
      (Phase 1 Stage 11) already fails the suite if any new Project/Task
      route has no row, so this is enforced structurally, not by discipline
      alone. Explicitly includes project-member-management rows (decision 6)
      covering all four cases: `MANAGER`/`ADMIN`/`OWNER` (allowed via role),
      a `MEMBER` who owns the project (allowed via ownership — the case a
      route-only check would have missed), a `MEMBER` who doesn't own it
      (403), and the isolation-matrix row (org B's member, owner or not,
      against org A's project — 404).

      **Audit first, then fill the actual gap.** The authz-matrix side was
      already complete going into this stage: every ownership-split route
      (project-member management, task write, checklist items, attachment
      upload/delete, comment author-only edit/ADMIN-delete) already had a
      dedicated multi-way test covering the real cases — including a
      `cross_org` row — built incrementally during Stages 2–7's own review
      rounds, not deferred to here. `test_matrix_covers_every_permission_
      gated_route`'s meta-assertion was already green with 438 tests
      passing before this stage touched anything, confirming no route was
      silently missing a row. The actual gap was `test_isolation_matrix.py`
      itself: it only had Team's routes (Phase 1 Stage 11) — every Phase 2
      resource's cross-org check so far lived as a single-role (usually
      ADMIN) spot-check inside that resource's own integration test file
      (`test_projects.py`, `test_tasks.py`, etc.), never broadened to
      "every role, not just the one that happened to be convenient," the
      way Team's own `test_every_role_in_org_b_gets_404_for_org_as_
      membership` already was.

      Added `test_work_resources_isolated_across_orgs` (15 routes ×
      4 roles): project/board/members/milestones reads, task read/write/
      delete, comment CRUD, checklist-item CRUD — every org-B role against
      an org-A project/task/comment/checklist item, asserting 404.
      `test_attachment_routes_isolated_across_orgs` (4 roles) covers
      upload/download/delete separately, since upload is multipart and
      needs the `FileStorage` dependency override (ADR-0008), not a
      `json=` body like the rest.

      **A real, if narrow, finding surfaced while writing the generic
      table**: `PATCH`/`DELETE /api/v1/projects/{id}` aren't like the
      other routes here — `PROJECT_WRITE`/`PROJECT_DELETE` are hard
      `MANAGER+`/`ADMIN+` role-tier gates with no `MEMBER`-tier
      reachability at all (unlike every ownership-split route, which
      *is* reachable by every role at the route layer and relies on the
      service to split further). Running the generic "every role, 404"
      assertion against them meant a `MANAGER` (for `DELETE`) or `MEMBER`
      (for either) got a legitimate 403 — they lack the permission
      outright, in *any* org, not just org B — which the test flagged as
      a failure even though nothing was actually wrong. Not a security
      bug: testing isolation with a role that can't reach the route at
      all doesn't test isolation, it just re-proves the role/permission
      table. Split into `test_project_write_routes_isolated_across_orgs`,
      parametrized over only `ADMIN`/`OWNER` (the roles that actually hold
      `PROJECT_DELETE`, the stricter of the two), with the two routes
      removed from the generic table and a comment there explaining why.

      Activity feed isolation isn't a new test here — `test_activity_
      feed.py`'s `test_activity_feed_is_org_scoped` (Stage 7) already
      covers it; a list route's "never leaks another org's rows" shape
      doesn't fit the per-resource-404 table anyway (same reasoning
      Team's own list-isolation test predates this file's per-resource
      rows for the same reason).

      506 tests passing (was 438 — 68 new: 15×4 generic + 4 attachment +
      4 project-write). No backend logic changed, no migrations, no
      OpenAPI diff (test-only stage). Ruff, mypy, full suite all green.

      **Codex review: `make check` wasn't actually green** — I'd been
      running `pnpm lint`/`typecheck`/`test`/`build` individually all
      stage, never `make lint`/`make check` themselves, so `prettier
      --check .` (part of `make lint`, not `pnpm lint`, which only runs
      ESLint) never actually ran. Four Stage 8 files were unformatted:
      `dashboard/page.tsx`, `kanban-board.tsx`, `lib/api/client.ts`,
      `tests/project-detail.test.tsx` — fixed with `prettier --write .`,
      re-verified with `prettier --check .` and a full `make check` run
      end to end this time, not the individual commands standing in for
      it. Also removed an untracked `.pnpm-store/` directory `make check`
      had created locally and added it to `.gitignore` (a stray pnpm
      cache path, not a project file). No source logic changed — purely
      formatting plus the ignore-list addition.
- [x] Stage 10 — `scripts/seed.py` extended (decision 4 above). Two
      projects: "TrinolIT Website" (`WEB`) and "Trinol OS" (`TOS`, the
      internal-product project — dogfooding the product itself rather
      than inventing an unrelated placeholder), each owned by Founder
      with Developer and Designer as `project_members` (so every seed
      role can actually see both projects under RBAC.md §3's "Project
      detail" rule — `MANAGER+` or membership — not just the OWNER).
      Five tasks per project, one per `TaskStatus`, priorities spread
      across all four `TaskPriority` values and assignees rotated across
      the three seed users — enough to exercise the Kanban board and
      dashboard tiles realistically per decision 4, without inventing
      Phase 3/CRM data (`client_id` stays null). Idempotency matched on
      each project's code, each (project, user) project-member pair, and
      each (project, title) task pair — same per-entity tracking already
      established for users/memberships (Stage 12 of Phase 1), extended
      to the three new entity types in `test_seed_idempotent.py`.

      **Found and fixed a real, pre-existing bug while running `make
      seed` for real, not just adding rows to the script**: the CLI
      entry point (`python -m trinol.scripts.seed`) has been broken
      since Phase 2 Stage 6 added `organizations.logo_file_id`'s
      composite FK to `file_objects` — `scripts/seed.py` never imports
      `trinol.platform.models`, so SQLAlchemy's mapper registry never
      resolves that FK, and flushing the very first `Organization` row
      crashes with `NoReferencedTableError`. Invisible until now because
      every test that exercises `seed()` runs inside the same pytest
      session as `tests/conftest.py`'s own imports (which pull in
      `trinol.main` transitively, registering `platform.models` as a
      side effect before `seed()` ever runs) — the standalone CLI path
      has no such import chain. `migrations/env.py` already had the
      identical fix for the identical reason (`from trinol.platform
      import models as _platform_models  # noqa: F401`, for exactly its
      documented side effect); applied the same one-line fix to
      `scripts/seed.py`. Confirmed by reverting to the pre-fix version
      and reproducing the crash (`git stash`), not just reasoning about
      it — same empirical-verification discipline as every other schema-
      adjacent finding this phase.

      A second bug surfaced while extending `test_seed_idempotent.py`'s
      cleanup: it only ever tracked Organization/User/Membership, so once
      `seed()` also creates Projects (whose `owner_id` is a composite FK
      to `memberships`), a naive cleanup that deletes memberships before
      projects hits `fk_projects_org_owner_memberships` — the identical
      *shape* of bug the Stage 12 (Phase 1) Codex review already found and
      fixed once for Organization/User, now recurring at the next entity
      layer down. Fixed by extending the same per-entity snapshot/cleanup
      pattern to projects, project members, and tasks, deleting in FK-safe
      order (tasks and members before their project, projects before the
      memberships they reference). Reproduced against a genuinely fresh
      local DB (not just reasoned about) before and after the fix to
      confirm it was real.

      `make seed` run twice against the real local Postgres and verified
      directly via `psql`: exactly one row per project, five tasks each,
      no duplication. Full suite (506 tests, unchanged — existing tests
      strengthened with project/task assertions, not new test count),
      ruff, mypy, `make check` end to end (backend + frontend + OpenAPI
      diff) all green.

      **Codex review: `test_seed_idempotent.py`'s tests assumed the real
      `trinolit` org/emails never pre-exist** — true against CI's always-
      fresh database, but false the moment a developer actually runs
      `make seed` against their own persistent local Postgres and then
      the test suite, exactly the workflow this very stage's own commit
      message documented running. Reproduced directly: ran `make seed`
      for real, then `pytest`, and watched both partial-state tests fail
      immediately on `assert not pre_snapshot.organization_existed`.
      Fixed with a new `_isolated_seed` fixture that monkeypatches
      `scripts/seed.py`'s own module-level constants (`_ORG_SLUG`,
      `_SEED_USERS`, `_SEED_PROJECTS`) to a uniquely-suffixed shadow
      dataset — a fresh org slug and seed-user emails generated per test
      run — so every test in this file exercises the exact same `seed()`
      code path against data that can never collide with a real,
      already-seeded `trinolit` org, rather than assuming one doesn't
      exist. All three tests, `_snapshot()`, and `_cleanup_rows_created_
      since()` now read these constants dynamically off the module
      object (`seed_module.X`) instead of names imported once at collection
      time, so the monkeypatch and every helper stay in sync. Re-verified
      by running `make seed` for real again, confirming the org existed,
      then running the full suite (506 tests) directly against that
      state — passes cleanly, the exact reproduction of the reported
      failure now fixed, not merely reasoned about. `make check` also
      re-run end to end immediately after `make seed`, matching the
      documented workflow exactly.
- [x] Stage 11 — E2E foundation (Playwright) — first real page with content
      to click through; TESTING.md §5 already scopes this to
      main/release-candidate runs, not every PR

      **Decision needed first, not inferable from the docs**: TESTING.md
      §5 lists "login" as one of the eight E2E flows and says Playwright
      runs "against the docker-compose stack with seeded data," but
      nowhere specifies *how* an external browser process is supposed to
      authenticate — the in-process `FakeIdentityVerifier` pytest already
      uses only works via `app.dependency_overrides`, unreachable from a
      separately-running server Playwright hits over real HTTP, and there
      are no real Firebase test credentials in any environment this
      project has run in so far. Asked the user directly rather than
      guessing at a security-relevant design point; chose "add a gated
      test-only auth bypass" over waiting on real credentials or mocking
      Firebase client-side.

      **Implementation.** `Settings.e2e_test_mode: bool = False`
      (core/config.py) and a new `E2EIdentityVerifier`
      (identity/e2e_verifier.py): `verify(id_token)` treats `id_token` as
      the plain email of a pre-existing user and returns
      `firebase_uid=f"seed-{email}"`, matching `scripts/seed.py`'s own
      placeholder scheme exactly (`_resolve_or_provision_user` matches
      strictly on `firebase_uid`, so this has to line up, not just look
      plausible) — the seeded Founder/Developer/Designer users resolve
      correctly with no new account provisioning. `get_identity_verifier()`
      (identity/deps.py) hands out `E2EIdentityVerifier` only when
      `e2e_test_mode` is on **and** `app_env != "production"` — checked at
      the call site, not left to the settings default alone, so a
      misconfigured production deployment can't honor the flag even if
      `E2E_TEST_MODE` is accidentally set there (same defense-in-depth
      posture as EMAIL.md §3's dev-only SMTP allowlist). 4 new unit tests
      (`test_e2e_identity_verifier.py`) cover the verifier's identity
      output and all three gating branches directly — a security-relevant
      gate gets the same direct-test treatment as origin_check/
      authz_matrix, not just indirect coverage via the E2E spec itself.

      Frontend: `login/page.tsx` renders a second, minimal form only when
      `NEXT_PUBLIC_E2E_TEST_MODE=true` (unset by default — never in a real
      deployment) — a plain email field that calls the exact same
      `completeSignIn()` the real form uses, so CSRF-token handling and
      the post-login redirect are identical, not a separate code path
      that could drift. The backend's own gate is the actual security
      boundary; this is a convenience the backend would refuse anyway if
      it were somehow reachable in production. Both `.env.example`
      variables documented, default `false`.

      `playwright.config.ts` (`apps/web`, Chromium only, no `webServer` —
      runs against a stack the caller already has up, per TESTING.md §5's
      own wording) and `e2e/smoke.spec.ts`: log in, create a project,
      create a task assigned to that project, drag it from TODO to DONE
      on the Kanban board, assert it landed. `vitest.config.ts` excludes
      `e2e/**` — Playwright's own `test`/`expect` globals collide with
      vitest's default include glob otherwise.

      **Two real, pre-existing gaps found while actually driving the app
      end to end, not by reading the code — neither is Stage 11's own
      new surface, both predate it:**

      1. **A task created via the UI could never appear on any Kanban
         board.** The Stage 8 create-task form never collected a
         `project_id` — every task-via-UI landed with `project_id: null`,
         and `GET /projects/{id}/board` groups strictly by `project_id`.
         "Create a task, move it on the board" (TESTING.md §5's own
         flow) was structurally impossible through the app as it stood.
         Fixed: `CreateTaskForm` (`components/tasks/task-list.tsx`) gained
         a "Project (optional)" `<select>`, populated from
         `fetchProjects()`, submitting `project_id` when one's chosen.

      2. **CSRF token never survived a fresh page load of an
         already-authenticated session.** `lib/api/client.ts`'s
         `csrfToken` is deliberately in-memory only (AUTH.md §6) and was
         only ever set once, right after the login form's own
         `completeSignIn()` — true for a real user's uninterrupted SPA
         session, but any full navigation (`page.goto()` in Playwright;
         equally a hard refresh or a new tab for a real user) wipes it
         with nothing to restore it, so the very next POST/PATCH/DELETE
         403s with "Invalid or missing CSRF token." Reproduced directly
         (the smoke spec's own `page.goto("/projects")` after login hit
         exactly this) before fixing it, not just reasoned about. Fixed
         by extending `app/(app)/layout.tsx`'s existing server-side
         `fetchSessionInfo()` call (already resolving `role` for
         Sidebar) to also read `csrf_token`, passed into `AppShell` (now
         a required prop) which rehydrates it via `setCsrfToken()` in a
         `useEffect` — covers every page in the authenticated app on
         every fresh load, not just the login form's own one-time set.

      **Manual verification, complete this time — not partial.** Ran the
      full flow for real: `make seed` (already had run in Stage 10),
      backend started with `E2E_TEST_MODE=true` and `APP_ORIGIN` matching
      the actual dev-server port, frontend started with
      `NEXT_PUBLIC_E2E_TEST_MODE=true`, Chromium installed via
      `pnpm exec playwright install chromium` (works in this environment,
      unlike the MCP Playwright plugin's own separate Chrome dependency
      hit in Stage 8). `pnpm exec playwright test` failed twice first —
      an Origin mismatch (a real dev-server port collision, fixed by
      matching `APP_ORIGIN` to it) and the CSRF gap above (fixed for
      real, in the app, not worked around in the test) — then passed
      clean on the third run. Test-created rows (`E2E<timestamp>`
      project/task) cleaned up afterward via `psql`; the real seed data
      from Stage 10 confirmed untouched (still exactly 2 projects, 10
      tasks). 510 backend tests passing (was 506), 22 frontend tests
      passing (was 20). `make check` re-verified green end to end
      afterward — ruff, mypy, ESLint, Prettier, typecheck, Vitest,
      `next build`, OpenAPI diff.
- [x] Codex audit — conducted per-stage throughout Phase 2 (Stages 1–11), not as one end-of-phase pass; every stage above was independently reviewed and re-verified before the next began, per AGENTS.md's gate rule.
- [x] Resolve P0/P1 findings — every finding raised across all 11 stages was resolved and re-verified; none remain open. Codex's final Phase 2 audit: "approved... no P0/P1/P2 findings," independently re-verifying the E2E verifier's production gate, CSRF rehydration, project-linked task creation, and the full test suite (510 backend, 22 frontend) plus `make check` end to end.

## Phase 3 — CRM

Status: **APPROVED by Codex.** All 11 stages complete and independently
reviewed; the final Phase 3 audit found no P0/P1 findings.

Unlike Phase 1 (new architecture) and even Phase 2 (which still had to
invent one new permission mid-plan), Phase 3 needed zero new architecture
decisions and zero new `Permission` enum values — `DATABASE.md` §3,
`RBAC.md` §2, `SECURITY.md` §5, `EMAIL.md` §5, and `ARCHITECTURE.md` §3
already fully specified the `crm` module's tables, permission matrix, the
public contact endpoint's security envelope, the email flow, and the exact
cross-module boundary (lead conversion lives in `work.services.
convert_lead`, `crm` must never import `work`). `LEAD_READ`/`CLIENT_READ`/
`LEAD_WRITE`/`CLIENT_WRITE`/`LEAD_CONVERT` were already sitting in the
`Permission` enum, correctly tiered, since Phase 1 Stage 6.

One open question, flagged rather than silently resolved during planning:
RBAC.md §2 has no per-resource ownership-split row for leads/clients
(unlike Phase 2's task-edit/project-detail/project-member-write rules) —
the matrix is role-threshold only. Decision: no ownership-split rule this
phase — `assigned_to`/`owner_id` are visibility/audit fields only, not an
authorization escape hatch. A second stated assumption: archive reuses
`LEAD_WRITE`/`CLIENT_WRITE` (no distinct delete permission exists in
RBAC.md, unlike `PROJECT_DELETE`).

Exit criteria: a MANAGER+ can create a lead, walk it through every
pipeline stage via drag-and-drop, and convert it to a client + project in
one action; any MEMBER can view leads/clients/pipeline read-only; the
public contact form creates a lead end-to-end with rate limiting and spam
checks; dashboard sales tiles show real counts.

- [x] Stage 1 — `crm` module schema. `modules/crm/models.py`: `Client`,
      `Lead`, `LeadStageEvent`, `ContactSubmission` — exact columns/
      constraints from DATABASE.md §3 (crm section), composite FKs to
      `memberships(organization_id, user_id)` for `clients.owner_id`/
      `leads.assigned_to` (§5.1), `ON DELETE RESTRICT` throughout (§5.2 —
      deactivation, not deletion, is the supported path). `Client`/`Lead`
      get `archived_at` (ADR-0011); `LeadStageEvent`/`ContactSubmission`
      don't (history/raw-record tables, never archived).
      `modules/work/models.py`: added the one deferred column now that
      `clients` exists — `Project.client_id`, composite FK to
      `clients(organization_id, id)`, `RESTRICT` (a client is soft-deleted
      only; an unexpected hard delete under a linked project should fail
      loudly, same reasoning Phase 2 used for `milestones.project_id`).
      `migrations/versions/0005_crm_schema.py`: new tables + the
      `projects.client_id` column/FK/index in one migration, hand-written
      raw SQL matching `0003`/`0004`'s exact style (native enums,
      `CREATE TRIGGER ... set_updated_at()`, composite FK comments). No
      `Permission` enum change needed — confirmed directly, already
      present and correctly tiered since Phase 1 Stage 6.

      **A real, if narrow, finding surfaced while verifying this stage,
      not assumed from the plan.** `tests/security/test_schema_integrity.
      py`'s generic composite-FK checks derive which tables to check from
      `Base.registry.mappers` filtered by `OrgScoped` — but that set only
      reflects a module if something has actually imported it. The file
      itself only ever imported `identity`/`platform` models directly;
      `work` was checked only *by accident*, because `tests/factories.py`
      (loaded by every test session via `conftest.py`) already imports it
      for `make_project`/`make_task`. `crm` has no such accidental import
      yet (that lands in a later stage, alongside `make_client`/
      `make_lead`), so without a fix, `_ORG_SCOPED_TABLES` silently
      excluded `clients`/`leads`/`lead_stage_events`/`contact_submissions`
      entirely — both composite-FK tests passed on my new tables, but
      vacuously: they never actually looked at them. The exact *shape* of
      bug Phase 2 Stage 6 already found once for a different reason (that
      time a Postgres privilege-visibility issue; this time a Python
      import-completeness gap). Fixed by explicitly importing `work` and
      `crm` models directly in the test file itself (mirroring
      `migrations/env.py`'s own explicit-import discipline), rather than
      relying on incidental transitive imports from other test modules.
      Verified empirically, not just reasoned about: confirmed via a
      direct Python check that `clients`/`leads` were absent from
      `_ORG_SCOPED_TABLES` before the fix and present after; deliberately
      added a real single-column FK (`leads.scratch_client_ref -> clients.
      id`) via `psql` and confirmed the fixed test now genuinely fails on
      it, then reverted — matching the exact verification discipline
      Phase 2 Stage 6 established for its own version of this bug class.

      A second, smaller finding from a manual audit against DATABASE.md
      §1's "every FK has a supporting index" rule (no automated test
      covers this — Phase 2 Stage 1's own version of this gap was only
      ever caught by manual Codex review, not a test): `fk_leads_org_
      converted_client_clients` had no supporting index. Added
      `ix_leads_org_converted_client`.

      Full suite (510 tests, unchanged count — no new tests added this
      stage beyond the schema-integrity fix, which strengthens existing
      assertions rather than adding new ones), ruff, mypy, `alembic
      upgrade`/`downgrade -1`/`upgrade`/`check` (run twice, after the
      index fix too) all clean, `make check` end to end (backend +
      frontend + OpenAPI diff, unaffected this stage) green.
- [x] Stage 2 — Client CRUD. `modules/crm/schemas.py`:
      `ClientCreateRequest`/`ClientUpdateRequest` (partial,
      `exclude_unset=True`)/`ClientResponse`/`ClientListResponse`
      (`{items, total}`, ADR-0005). `modules/crm/services/
      client_service.py`: `create_client`/`list_clients`/`get_client`/
      `update_client`/`archive_client`, mirroring `project_service.py`'s
      exact shape — soft-delete via `archived_at` (ADR-0011), `GET
      /clients` excludes archived by default. `modules/crm/routes/
      clients.py`: `POST/GET/GET{id}/PATCH/DELETE /api/v1/clients`, each
      gated on `Permission.CLIENT_READ` or `CLIENT_WRITE` — archive also
      `CLIENT_WRITE` (Context's stated assumption: no distinct delete
      permission exists in RBAC.md for clients, unlike `PROJECT_DELETE`).
      Registered in `main.py`. `tests/integration/test_clients.py`: role
      gating (MANAGER+ create, every role views), owner-membership
      validation, archive-excluded-from-list, partial update, null
      rejection on required fields, cross-org 404.

      **A structural requirement the plan's own Stage 2 text didn't
      call out, found while actually running the suite, not assumed**:
      `test_authz_matrix.py`'s meta-assertion
      (`test_matrix_covers_every_permission_gated_route`, Phase 1 Stage 11)
      fails the *entire* suite the moment any new permission-gated route
      has no matrix row — checked directly against git history, this
      meant every one of Phase 2's own stages (2 through 7) added its
      own routes' matrix rows in the same commit, not deferred to a
      single "security matrices" stage the way the plan's Stage 9
      wording implied. Added the five new client routes to `_MATRIX_
      ROWS` and a `{client_id}` resolution branch (mirroring
      `{project_id}`'s) to the generic per-role test, plus a new
      `make_client` factory in `tests/factories.py` (needed regardless —
      Stage 9 would have added it anyway for isolation-matrix rows).
      Full per-resource ownership-split testing and cross-org isolation
      rows for clients still land in Stage 9 as planned; only the bare
      per-route/per-role coverage the meta-assertion structurally
      requires was pulled forward.

      550 tests passing (was 510 — 15 `test_clients.py` + 5 new matrix
      rows × 4 roles = 20, plus the meta-assertion itself continuing to
      pass), ruff, mypy, `make openapi` regenerated (new diff for the
      five client operations, expected and committed alongside), `make
      check` green end to end (backend + frontend; the one intentional
      OpenAPI diff is the commit's own content, not drift).
- [x] Stage 3 — Lead CRUD + stage transitions. `modules/crm/schemas.py`:
      `LeadCreateRequest`/`LeadUpdateRequest`/`LeadResponse`/
      `LeadListResponse`; `estimated_value`/`board_position` use a
      decimal-string `Annotated` type duplicated from `work/schemas.py`'s
      `BudgetDecimal`/`BoardPositionDecimal` rather than imported (crm must
      not import work — ARCHITECTURE.md §3 — applies to a plain Python
      import too, not just business logic; small enough to duplicate once).
      `modules/crm/services/lead_service.py`: `create_lead`/`list_leads`
      (filterable by `stage`/`assigned_to`)/`get_lead`/`update_lead`/
      `archive_lead`, plus `change_lead_stage` (writes the `lead_stage_
      events` row in the same transaction, DATABASE.md §3). `modules/
      crm/routes/leads.py`: `POST/GET /leads`, `GET/PATCH /leads/{id}`,
      `DELETE /leads/{id}` (archive) — gated on `LEAD_READ`/`LEAD_WRITE`.

      **A real self-contradiction in this plan's own Stage 3/Stage 4 text,
      resolved by finding a closer-fitting existing precedent than the one
      the plan reached for.** Stage 3's text said `stage` should be
      excluded from `LeadUpdateRequest` behind a dedicated `POST
      /leads/{id}/stage` route ("one source of truth," reasoning by
      analogy to `TaskUpdateRequest` excluding `completed_at`) — but Stage
      4's own text then required the *general* `PATCH /leads/{id}` to
      accept `stage` directly for drag-across-columns. Re-reading
      `modules/work/services/task_service.py`'s actual `update_task`
      before writing code (not just trusting the plan's summary of it)
      showed the analogy was wrong at the source: `TaskUpdateRequest`
      *does* accept `status` directly, and `update_task` detects the
      change inline and records the activity event itself — only the
      *derived* field (`completed_at`) is excluded, never `status` itself.
      Adopted the same shape for leads: `LeadUpdateRequest` includes
      `stage` and `board_position` as ordinary fields (matching
      `TaskUpdateRequest` exactly); `update_lead` captures the previous
      stage, applies updates, and calls `change_lead_stage` inline when
      `stage` changed — writing the `lead_stage_events` row in the same
      transaction as the DB commit either way. No dedicated stage-change
      route exists; this resolves the contradiction and removes a route
      Stage 4 would otherwise have had no real use for. `converted_client_
      id`/`converted_at` stay excluded from `LeadUpdateRequest`, mirroring
      `completed_at`'s exclusion correctly this time — set only by Stage
      5's `work.services.lead_conversion_service.convert_lead`.

      `ck_lead_contact` (email or phone required) is checked at the
      Pydantic layer for `LeadCreateRequest` (full state available) and,
      for `LeadUpdateRequest`, only when a request explicitly nulls both
      fields in the same body — a request touching only one of the two
      can't be validated without the row's other current value, so
      `update_lead` also catches the DB's own `IntegrityError` on that
      constraint and translates it to a clean 422, the same
      `_violates_constraint` pattern `project_service.py` already
      established for `uq_project_org_code`.

      Added the five new lead routes' authz-matrix rows and a
      `{lead_id}` resolution branch (same requirement Stage 2 found —
      the meta-assertion needs this immediately, not deferred), plus a
      `make_lead` factory. `tests/integration/test_leads.py`: role
      gating, `ck_lead_contact` validation (both at creation and via the
      partial-update/IntegrityError path), every one of the seven legal
      stage transitions asserting exactly one `lead_stage_events` row
      with correct `from_stage`/`to_stage`/`actor_id`, a same-stage PATCH
      and an unrelated-field PATCH both asserting *zero* stage-event rows
      (proving the "only on a real change" guard works both ways), list
      filtering by `stage`, archive-excludes-from-list, cross-org 404.

      600 tests passing (was 550). `make openapi` regenerated for the
      five new lead operations. `make check` green end to end.
- [x] Stage 4 — Pipeline board endpoint + drag reorder.
      `modules/crm/services/pipeline_service.py`: `get_pipeline_board`
      groups an org's non-archived leads by `stage`, ordered by
      `board_position asc, id asc` — same shape as `board_service.py`'s
      `get_project_board`, including the identical "bounded in practice"
      500-lead cap (Phase 2 decision 3, not a fresh judgment call).
      `modules/crm/routes/pipeline.py`: `GET /api/v1/pipeline`, a
      top-level route (pipeline is org-wide, no parent resource — the
      one route in `crm` that isn't nested under `/clients` or `/leads`,
      mirroring `platform/routes/activity.py`'s single-route-file
      precedent), gated on `LEAD_READ`. Drag reorder needed no new
      endpoint at all (Phase 2 decision 1's identical pattern): Stage 3's
      `PATCH /leads/{id}` already accepts both `board_position` and
      `stage` as ordinary fields in one request, so a drag-across-columns
      UI action is just one PATCH call.

      Caught and fixed one naming-convention slip before it shipped:
      `routes/leads.py`'s response-mapping helper was `_lead_to_response`
      (leading underscore), but `routes/pipeline.py` needed to import it
      to build `PipelineColumn`'s lead lists — the established convention
      for a helper reused across route files within a module has no
      leading underscore (precedent: `task_to_response` in
      `routes/tasks.py`, imported by `routes/projects.py`). Renamed to
      `lead_to_response` at all six call sites rather than duplicating
      the mapping logic in `pipeline.py`.

      Added the new route's authz-matrix row (`LEAD_READ`, no
      `{lead_id}`-style placeholder to resolve — pipeline has no parent
      resource, so no `_OWNERSHIP_SPLIT_ROUTES` branch was needed either).
      `tests/integration/test_pipeline.py`: groups leads by stage
      correctly, orders within a column by `board_position`, caps at 500
      and reports `truncated` honestly, every role can view, a drag
      (`stage` + `board_position` in one PATCH) writes exactly one
      `lead_stage_events` row, a same-column reorder (`board_position`
      only) writes zero.

      614 tests passing (was 600). `make openapi` regenerated for the
      new pipeline operation. `make check` green end to end.
- [x] Stage 5 — Lead conversion (the one genuinely cross-module stage).

      **A real error in this plan's own Stage 5 text, caught before writing
      any code, not after.** The plan said the new route "lives in `crm`
      ... delegates entirely to `work.services.lead_conversion_service.
      convert_lead`" — but re-reading ARCHITECTURE.md §3 directly (rather
      than trusting the plan's own paraphrase of it, the same discipline
      Stage 3's self-contradiction taught) shows the rule is one-way: "`crm`
      must not import from `work`", `work → crm` is the one explicitly
      allowed direction. A route *file* living in `modules/crm/routes/`
      that imports a `work` service function would itself be a `crm →
      work` import — exactly the violation the rule forbids. So the route
      is NOT in `crm`: `modules/work/routes/lead_conversion.py` owns `POST
      /api/v1/leads/{lead_id}/convert` (the URL is leads-shaped; the
      owning module isn't — nothing requires the two to match), registered
      in `main.py` alongside `work`'s other routers. `modules/work/
      services/lead_conversion_service.py` imports `Lead`/`Client` and
      `lead_service.change_lead_stage`/`ensure_actor_in_org`/
      `get_lead_in_org` from `crm` — the one direction the rule allows —
      and builds the `Client`+`Project` rows directly (not by calling
      `create_client`/`create_project`, which each commit their own
      transaction — Stage 5's proof requires one transaction for
      everything, so only their row-construction shape is reused, not the
      self-committing functions themselves). `LeadConversionResponse`
      (`{lead, client, project}`) lives in `work/schemas.py` for the same
      reason, importing `crm.schemas.LeadResponse`/`ClientResponse`.

      No project_code generator exists anywhere in the codebase to "reuse"
      (`create_project` takes a client-supplied code, confirmed directly —
      the plan's assumption that one existed was wrong too) — added a
      small `_project_code_from_lead` (name slug + random suffix) local to
      the new service, `ponytail:`-flagged: a real collision surfaces as a
      409 rather than a retry loop, upgrade if it ever actually fires.

      Hit the exact `org_session.py` guard trap Phase 2 hit twice, this
      time via a new path: the lead is *updated* (not inserted) in this
      transaction, so its `updated_at` (`server_onupdate=FetchedValue()`)
      comes back expired after commit, and a bare lazy-reload on next
      access has no `organization_id` predicate. `update_lead` already
      works around this by re-fetching org-scoped after its own commit —
      applied the identical fix here for `lead` only; `client`/`project`
      are fresh inserts whose defaults were already captured via
      `RETURNING` at flush time, so they don't need it.

      Caught two more naming-convention slips before they shipped, same
      class of fix as Stage 4's `lead_to_response` rename: `routes/
      clients.py`'s `_client_to_response` and `routes/projects.py`'s
      `_project_to_response` both needed to lose their leading underscore
      once `lead_conversion.py` needed to import them to build the
      combined response — renamed both (6 and 5 call sites respectively).
      Also extended `ProjectResponse`/`project_to_response` with
      `client_id` (present on the model since Stage 1, never surfaced
      until now).

      `convert_lead`: loads the lead (404 cross-org/missing via the
      existing `get_lead_in_org`), 409s if already archived or already
      converted, creates the `Client` (`owner_id = actor` — the lead's own
      `assigned_to` may be unset) and `Project` (`client_id` set,
      `owner_id = actor`, added as a `project_members` LEAD row, mirroring
      `create_project`'s own invariant), stamps `converted_client_id`/
      `converted_at`, transitions `stage` to `WON` via the same
      `change_lead_stage` helper from Stage 3 — unconditionally, even if
      the lead happened to already be at `WON`, since conversion is itself
      a significant event worth recording, not a no-op to skip — and
      records `client.created`/`project.created` (ordinary feed) plus
      `lead.converted` (`is_audit=true`, MASTER_PROMPT §28), all in the one
      transaction the Proof section requires.

      Added the new route's authz-matrix row (`LEAD_CONVERT`, the existing
      `{lead_id}` resolution branch already covers it generically — no new
      branch needed). `tests/integration/test_lead_conversion.py`: a
      single conversion creates exactly one `Client`/`Project` with
      `project.client_id` correctly set, stamps the lead's conversion
      fields, writes exactly one `lead_stage_events` row and all three
      activity rows with correct `is_audit` flags; MEMBER 403s; a second
      conversion attempt and converting an archived lead both 409; cross-
      org 404.

      624 tests passing (was 614). `make openapi` regenerated for the new
      convert operation and `ProjectResponse.client_id`. `make check`
      green end to end. A `grep -rL "from trinol.modules.work"
      apps/api/src/trinol/modules/crm` confirms `crm` still never imports
      `work`, even after this stage.

      **Codex P1 (real, fixed):** `convert_lead`'s archived/already-
      converted check was a bare check-then-write with no lock — two
      concurrent conversions of the same lead could both pass it, each
      create their own `Client`+`Project`, then race to stamp
      `converted_client_id`, orphaning one client/project and breaking
      the one-to-one invariant. Fixed by adding `for_update: bool = False`
      to `lead_service.get_lead_in_org` (chains `.with_for_update()`) and
      passing `for_update=True` from `convert_lead` — the second
      concurrent request blocks on the lead row's lock instead of racing,
      then (Postgres re-fetches the row under `FOR UPDATE` per READ
      COMMITTED) sees `converted_client_id` already set and 409s. Same
      shape as `organization_lock.py`'s existing lock, just scoped to one
      row instead of the whole org — locking the org here would
      needlessly serialize unrelated leads' conversions too.
      `test_concurrent_conversion_of_the_same_lead_only_one_succeeds`:
      two genuinely independent DB sessions (not two SAVEPOINTs sharing
      one transaction — the point is Postgres actually serializing them),
      mirroring `test_invitations.py`'s existing duplicate-invitation race
      test exactly; asserts exactly one success, one `ConflictError`, and
      exactly one `Client`/`Project` row survives. Passed 5/5 on repeat.

      625 tests passing (was 624). `make check` green end to end (no
      OpenAPI diff this round — the fix is internal locking, no API shape
      change).

      **Codex P2 (real, fixed):** the new race test commits real rows
      against the real dev database via two independent sessions (the
      whole point — a rolled-back `db_session` fixture can't observe two
      genuinely concurrent transactions) but had no cleanup, so repeated
      local runs would accumulate orphaned organizations/leads/clients/
      projects. Added the same explicit FK-ordered cleanup
      `test_invitations.py`'s matching race test already establishes:
      `activity_events` first (needs the migrator role — `trinol_app` has
      no UPDATE/DELETE grant there, ADR-0006), then `lead_stage_events`/
      `project_members` (children), then `projects`/`leads`, then
      `clients`, then `memberships`/`users`/`organizations`. Verified
      empirically, not just reasoned about: captured exact row counts
      across all nine affected tables via a direct `asyncpg` query,
      reran the race test three more times, confirmed the counts were
      bit-for-bit identical after.
- [x] Stage 6 — Public contact endpoint, the one unauthenticated write in
      the system (SECURITY.md §5). `modules/crm/schemas.py`:
      `ContactSubmitRequest` (honeypot `website` field, client-echoed
      `rendered_at` for a minimum-fill-duration check, `message` capped at
      5000 chars) / `ContactSubmitResponse` (`{reference_number}` only —
      deliberately generic, "does not reveal whether a lead was created").
      `modules/crm/services/contact_service.py`: `submit_contact`, in
      order — three `check_rate_limit` calls (5/hr IP, 20/hr email, 100/hr
      global; SECURITY.md §5's exact numbers), each followed by its own
      `db.commit()` per `platform/rate_limit.py`'s own documented contract
      (an attacker about to be rejected is still throttled) — then store
      the raw `ContactSubmission` unconditionally, then create a `Lead`
      only for a real (non-spam) submission, commit, then build (never
      send — the route sends) the two emails. `modules/crm/routes/
      public.py`: `POST /api/public/contact`, `@public`, registered in
      `main.py`. Two new Jinja template pairs
      (`new_lead_notification.{html,txt}.jinja`,
      `contact_confirmation.{html,txt}.jinja`) and their `render_*`
      functions in `platform/email/render.py`, following
      `invitation.{html,txt}.jinja`'s exact existing pattern.

      `core/errors.py`: added `RateLimitedError.retry_after_seconds`
      (optional field, not a redesign — every other raiser simply never
      sets it) and a new `PayloadTooLargeError` (413) for the body cap
      below; the exception handler attaches `Retry-After` when present.
      `platform/rate_limit.py`'s `check_rate_limit` now sets
      `retry_after_seconds` to the fixed window's full length when it
      raises — an approximation (this limiter doesn't track precise
      remaining time), fine for a hint header.

      **A real error in this plan's own Stage 6 text, caught by re-reading
      SECURITY.md/DATABASE.md directly before writing code (the same
      discipline Stage 5's module-boundary error taught):** the plan said
      "the app's existing global cap is looser than this route needs" —
      there is no existing body-size cap anywhere in the app at all
      (confirmed directly by grep). Added one: `_enforce_body_size_cap`
      reads the real request bytes (not `Content-Length`, which a client
      can omit or lie about) via `await request.body()` — Starlette caches
      the body after that call, so FastAPI's own Pydantic-parsing
      dependency downstream reads the same cached bytes, never the stream
      twice — and 413s past 8 KiB, ahead of Pydantic parsing as
      SECURITY.md requires.

      **A second real deviation, also verified rather than assumed:**
      DATABASE.md's literal wording for resolving `organization_id` from
      `PUBLIC_CONTACT_ORG_SLUG` is "resolved once at startup, failing the
      boot if it does not exist" — `create_app()` has no async lifespan
      hook to run that DB round trip against, and the setting is
      legitimately expected to stay unset in dev/test (confirmed: CI's own
      `env:` block in `.github/workflows/ci.yml` sets only `APP_ORIGIN`/
      `DATABASE_URL`/`DATABASE_MIGRATION_URL`, never
      `PUBLIC_CONTACT_ORG_SLUG`) — a true boot-time hard fail would break
      every environment that hasn't configured it. `get_
      public_contact_organization_id` instead resolves lazily on first
      real request, cached in a module-level singleton (mirrors
      `get_email_sender`'s own pattern) — still fails loudly the first
      time the route is actually hit if the slug is unset or doesn't match
      a real org, just not at process boot. Two dedicated tests call the
      real function directly (bypassing the dependency override every
      other test uses) to prove both failure modes still work.

      **A third, environment-specific finding:** this repo's own `.env`
      (copied from `.env.example`, which ships `PUBLIC_CONTACT_ORIGIN=
      https://www.trinolit.com` as its committed default) already has the
      origin-check exception active, while CI's `env:` block never sets
      it — meaning `_allowed_origin_for("POST", "/api/public/contact")`
      genuinely returns a *different* value depending on which environment
      is running the suite. Every contact test computes its Origin header
      the same way `origin_check.py` itself resolves it (`public_contact_
      origin or app_origin`) rather than hardcoding either value, so the
      suite passes identically in both. This same discrepancy broke an
      *existing* test on first run: `test_authn_matrix.py`'s generic
      "every non-public route 401s without a session" test hit this route
      with the default `app_origin` header and got a 403 `ORIGIN_MISMATCH`
      instead (correct behavior — this env's `.env` really does restrict
      this path to a different origin) — added the route to that test's
      explicit `_TRULY_PUBLIC_ROUTES` exclusion list, since it has its own
      dedicated coverage in `test_contact.py` and a generic same-origin
      client was never going to test it meaningfully either way.

      **A fourth real bug, found empirically by a test failure, not
      reasoning:** the reference-number generator, `f"TRI-C-
      {uuid7().hex[:8].upper()}"`, produced a genuine duplicate-key
      constraint violation inside the six-requests-in-a-loop rate-limit
      test — because a UUIDv7's hex is mostly its time-ordered high bits,
      truncating it to 8 characters keeps almost no real randomness for
      calls made within the same millisecond. Replaced with
      `secrets.token_hex(4)` (genuinely random). Stage 5's
      `_project_code_from_lead` used the identical flawed pattern
      (`uuid7().hex[:6]`) — never caught there because no Stage 5 test
      happened to create two projects in quick succession — fixed
      identically (`secrets.token_hex(3)`) once the same bug class was
      understood, even though Stage 5 is already closed.

      Also found and fixed, empirically (not by inspection): a bare
      `background_tasks.add_task(sender.send, message)` — the exact
      pattern `invitation_service.py`/`routes/invitations.py` already use
      — does NOT actually guarantee "a mail failure never fails the HTTP
      response" (SECURITY.md §5's explicit requirement for this route).
      Proved this directly with a minimal repro: a background task's
      exception propagates through Starlette's `TestClient`/`ASGITransport`
      and re-raises into the calling test, because that harness has no
      real network boundary to swallow it the way a real ASGI server
      (uvicorn) does after the response is already on the wire. Added
      `_send_and_log_failures`, wrapping every `sender.send()` call in a
      try/except that logs instead of re-raising — makes the property
      structurally true regardless of which server drives the app, rather
      than true by accident of uvicorn's behavior. (The invitation flow's
      own bare pattern is left as-is — it has no equivalent documented
      "must never fail" requirement, and retrofitting it is out of scope
      here.)

      `tests/integration/test_contact.py`: happy path (creates
      `ContactSubmission` + `Lead` in that order, exactly 2 emails queued
      with correct `reply_to`); honeypot-filled and too-fast submissions
      (`spam_score` set, no `Lead`, no emails, still `202`); oversized body
      (>8 KiB) 413s before Pydantic parsing; a mocked always-raising
      `EmailSender` still returns `202`; a 6th request from the same
      (simulated) IP within the hour 429s with a positive `Retry-After`;
      both organization-resolver failure modes. `test_authn_matrix.py`
      updated for the route's origin-exception behavior (above).

      633 tests passing (was 625). `make openapi` regenerated for the new
      contact operation. `make check` green end to end.

      **Codex P1 (real, fixed): the 8 KiB cap wasn't actually enforced
      before parsing.** `_enforce_body_size_cap` was a route-level
      `Depends(...)` — proven directly (not just per Codex's word) that
      this runs too late: FastAPI reads and JSON-decodes the request body
      as part of resolving the endpoint's own body parameter, and for a
      *malformed* body that decode failure short-circuits straight to 422
      before any dependency, route-level or not, ever runs at all (a
      minimal repro confirmed the dependency's own call list stayed empty
      for a malformed+oversized body). The existing test only sent a
      well-formed oversized JSON body, which happened to let the
      dependency run — passing for the wrong reason, and never exercising
      the case that actually mattered. Fixed by moving enforcement to
      `core/security/body_size_cap.py`'s `BodySizeCapMiddleware` — pure
      ASGI, mirroring `origin_check.py`'s existing shape, registered
      *inside* `OriginCheckMiddleware` (added before it, so it ends up
      innermost) so an origin-mismatched request is rejected without ever
      touching the body. Buffers up to the cap while checking cumulative
      size per chunk (rejecting before buffering unboundedly past it), then
      replays the buffered bytes to the inner app via a synthetic
      `receive` so FastAPI's own body reading downstream is unaffected.
      Removed the now-dead route-level dependency and the `PayloadTooLargeError`
      class it was the only caller of (the middleware builds its own
      envelope directly, same as `origin_check.py` already does — pure ASGI
      middleware runs before FastAPI's exception-handler machinery is even
      reachable, so `core/errors.py`'s `AppError` path was never usable
      here in the first place). Added the malformed-oversized-body
      regression test Codex asked for, and verified directly that a
      mismatched-origin request still 403s before ever reaching the new
      middleware's body check (confirming the registration order).

      634 tests passing (was 633). `make check` green end to end (no
      OpenAPI diff — internal-only, no API shape change).
- [x] Stage 7 — Activity feed wiring for CRM events. Wired
      `platform.activity.record(...)` into `client_service.create_client`
      (`client.created`) and `lead_service.create_lead` (`lead.created`) —
      both ordinary feed content, `is_audit=false` (ROADMAP.md Phase 2
      decision 2). No new infrastructure — `list_feed`/`list_audit`
      already exist and are already exercised by Phase 2's feed route
      (`test_activity_feed.py` needed no changes, confirmed by running it:
      it exercises the route generically via project/task events, and
      already passes with CRM rows now flowing through the same
      mechanism).

      **A real design deviation from this stage's own plan text, decided
      before writing code, not after:** the plan said to wire
      `lead.stage_changed` into `lead_service.change_lead_stage` itself.
      That function is shared by two callers — `update_lead`'s PATCH path
      and Stage 5's `work.services.lead_conversion_service.convert_lead`
      — and recording there unconditionally would make *every* conversion
      also emit a redundant ordinary-feed `lead.stage_changed` event
      alongside its own, already-correct `lead.converted` *audit* event
      for the exact same transition (Stage 5's own design, `is_audit=
      true`, deliberately distinct from a plain drag-driven stage change).
      Recorded in `update_lead` instead, right after the `change_lead_
      stage` call, inside the same `if new_stage is not None and new_stage
      != lead.stage` guard — fires only for a real PATCH-driven change,
      never during conversion (which never goes through `update_lead` at
      all). Strengthened Stage 5's own conversion test with an explicit
      `assert "lead.stage_changed" not in activity_by_event` to prove this
      doesn't regress.

      A real, if minor, bug surfaced while running the new tests: two
      pre-existing Stage 3 tests call `create_lead` directly with a plain
      string (`source="WEBSITE"`) rather than a real `LeadSource` member,
      bypassing the schema layer's coercion — `lead.source.value` doesn't
      exist on a plain `str`. Fixed by dropping `.value` entirely
      (`LeadSource` is a `StrEnum`; a real member and a matching plain
      string serialize identically into JSON metadata either way,
      confirmed directly), rather than tightening what a direct
      service-level caller may pass.

      `tests/integration/test_activity_writer.py`: `client.created`/
      `lead.created` feed events (mirroring `test_create_project_writes_a_
      feed_event`'s exact shape), a lead stage-change feed event with
      correct `{from, to}` metadata, and an unrelated-field update writing
      no feed event (mirroring the project trio already established
      there).

      638 tests passing (was 634). `make check` green end to end (no
      OpenAPI diff — no route/schema changes this stage).
- [x] Stage 8 — Frontend: Leads, Clients, Pipeline, dashboard, nav. The
      first frontend work in Phase 3 — every prior stage was backend-only.

      **One small backend addition, explicitly called for by this stage's
      own plan text, not scope creep:** the dashboard's "Pipeline Value"
      tile needed "a small service-side aggregate, not a client-side sum
      over a capped list" (the plan's own words, correctly followed rather
      than taking the easier client-side-sum shortcut). Added `GET
      /api/v1/leads/stats` (registered before `/leads/{lead_id}` — a
      static path must be matched first): `lead_service.get_lead_stats`
      sums `estimated_value` across non-archived, non-WON/LOST leads and
      counts leads with `next_follow_up <= today`. `ponytail`-flagged: sums
      across every lead's `estimated_value` regardless of `currency` — no
      org in real use today mixes currencies; a true multi-currency
      aggregate needs a per-currency breakdown, add it if that ever stops
      being true. New authz-matrix row (`LEAD_READ`, static path, same
      shape as Stage 4's `/pipeline`); `tests/integration/test_lead_
      stats.py` covers the sum/count logic and cross-org isolation
      directly (the matrix only proves role gating, not aggregate
      correctness).

      **A real, new frontend requirement this phase's own exit criteria
      states explicitly, unlike anything Phase 2 needed:** "Any MEMBER can
      view leads/clients/pipeline read-only — no create/edit/convert
      controls in the UI." Phase 2's Projects/Tasks pages never hid
      create/edit controls by role at all (confirmed by reading them
      directly) — because their real authorization rule is resource-
      specific (ownership/project-membership), a bare role check there
      would have been *wrong*. CRM's RBAC.md §2 rule is genuinely simpler
      (role-threshold only), so a plain role check is the whole story
      here, but nothing existing exposed the viewer's role to page content
      — `AppShell` only ever passed it to `Sidebar`. Added `lib/role-
      context.tsx` (`RoleProvider`/`useRole`/`useCanManageCrm`), wrapping
      `AppShell`'s children; every new page/component reads it to hide
      create/edit/convert buttons and, on the pipeline board, disable drag
      entirely (`draggable={false}`, not just a guarded network call) for
      a MEMBER.

      `lib/api/client.ts`: `fetchLeads`/`fetchLead`/`createLead`/
      `updateLead`/`archiveLead`/`convertLead`/`fetchLeadStats`,
      `fetchClients`/`fetchClient`/`createClient`/`updateClient`/
      `archiveClient`, `fetchPipeline` — mirroring `fetchProjects`/
      `fetchTasks`'s existing shape exactly. `app/(app)/leads/page.tsx`,
      `leads/[id]/page.tsx`, `clients/page.tsx`, `clients/[id]/page.tsx`
      (tabs: Overview + Projects real; Invoices/Payments/Meetings/
      Documents/Activity present but empty-state-only — Phase 4/5
      entities), `pipeline/page.tsx` — same client-rendered/four-state
      pattern Phase 2 Stage 8 established for Projects/Tasks/Team (a
      deliberate departure from ARCHITECTURE.md §5's server-rendered
      default, so every state is unit-testable against MSW).

      `components/board/pipeline-board.tsx`: a parallel component, not a
      generalized `<Board>` — the plan's own sanctioned fallback ("a
      parallel pipeline-board.tsx reusing the same drag logic is an
      acceptable fallback if full generalization proves awkward"), since
      `kanban-board.tsx` is tightly coupled to `TaskStatus`/task fields/
      `/tasks/{id}` and generalizing would need render-prop slots for two
      call sites. `computeBoardPosition` is duplicated, not shared,
      matching this codebase's own established precedent for a function
      this small (`crm/schemas.py`'s duplicated decimal validators, Stage
      4's own reasoning). `components/nav/sidebar.tsx`: SALES items flip
      from `aria-disabled` placeholders to real links.
      `app/(app)/dashboard/page.tsx`: "Open leads" placeholder replaced
      with a real "Total leads" count (same honesty-in-labeling fix
      Codex's Phase 2 Stage 8 review already made for tasks/projects), new
      "Pipeline value"/"Follow-ups due" tiles, and "New lead"/"New client"
      quick actions (MASTER_PROMPT §8) — not role-gated on the dashboard
      itself, since the destination pages already hide their own create
      controls from MEMBER.

      `ProjectsTab` (client detail) has no server-side `client_id` filter
      to call — `GET /api/v1/projects` never needed one before this stage
      — so it fetches a generously-capped list (`limit: 200`) and filters
      client-side, the same bounded-list-for-a-picker shape
      `task-list.tsx`'s own project picker already uses (`ponytail`-
      flagged in the code; add a real query param if a client's real
      project count ever approaches the cap).

      `tests/leads.test.tsx`, `lead-detail.test.tsx`, `clients.test.tsx`,
      `client-detail.test.tsx`, `pipeline-board.test.tsx`,
      `pipeline.test.tsx`: four-state coverage per list/detail page, MSW
      error-message-on-failure coverage mirroring `project-detail.test.
      tsx`'s pattern, and MEMBER-vs-MANAGER role-gating coverage (a new
      test dimension this stage introduces, since it's the first UI with a
      real role-based hiding rule). `sidebar.test.tsx` extended to confirm
      the three SALES items are now real links. Backend: 647 tests (was
      638 before this stage's stats-endpoint addition). Frontend: 46
      tests across 14 files (was 22 across 8 files before this stage).

      **Manually verified end to end**, not just unit-tested (this
      session's own CLAUDE.md instruction for UI work): ran the app
      directly (host-side `uv run uvicorn` + `pnpm dev` against the same
      Postgres the test suite uses, `E2E_TEST_MODE`/seeded `founder@
      trinolit.com` login, since Docker wasn't available in this
      environment) and drove a full Playwright script through login →
      create lead → view on pipeline → drag it to WON → convert to
      client+project → client detail's Projects tab shows the new project
      → dashboard tiles reflect the new counts.

      Two real environment findings surfaced during that walkthrough, both
      resolved without touching product code:
      - This machine had an unrelated, pre-existing process (a sibling
        "Trinol Payment" project's own uvicorn) already bound to
        `127.0.0.1:8000`, silently intercepting `localhost:8000` traffic
        while this project's own uvicorn sat bound to `0.0.0.0:8000`
        alongside it — confirmed via `lsof`, not assumed. Every automated
        test in this repo was unaffected (the whole suite drives the
        FastAPI app in-process via `ASGITransport`, never a real socket)
        — only this one manual, real-network walkthrough needed a
        different port to avoid it.
      - The pipeline board's drag-to-WON step initially appeared to fail
        silently in the default 1280px-wide headless viewport — the WON
        column (6th of 7) was laid out far outside that width, off the
        edge of what a synthetic drag can reach. Confirmed by checking the
        column's actual bounding box (`x: 1608`, past the 1280px
        viewport), then re-ran at a wider viewport where it worked
        correctly — the component logic was already correct; a real user
        on a narrow screen would need to scroll the board first, the same
        pre-existing limitation the Kanban task board already has at 5
        columns, just more noticeable at 7 (not a new problem introduced
        here, not fixed here — auto-scroll-on-drag-near-edge is a real
        enhancement but outside what Phase 2's own board ever built).

      **Codex P1 (real, fixed): `dropBeforeIndex` computed drag-and-drop
      neighbors from `column.leads` while it still contained the dragged
      lead at its old index.** Dragging a card past others downward could
      then pick the dragged card itself as a neighbor (sharpest when
      dropping onto the card immediately following the dragged one — that
      successor's "predecessor" resolved to the dragged card, still
      sitting in the array). Traced exhaustively before touching code:
      several "drag earlier card later" scenarios happened to produce a
      visually-correct final order anyway (removing an item before a
      lookup window shifts both ends equally, cancelling out) — but the
      immediate-successor case is different in kind, using the dragged
      card's own stale position as a stand-in for a real neighbor rather
      than computing from the cards actually surrounding the drop.
      Confirmed the discrepancy empirically (a throwaway RTL repro against
      the running component, not just arithmetic on paper) before
      committing to the fix.

      Replaced index-based `dropBeforeIndex(column, beforeIndex)` with
      `dropBeforeLead(column, targetLeadId)`: filters the dragged lead out
      of `column.leads` first, then locates the target by id in that
      filtered list — every neighbor lookup only ever sees cards other
      than the one being moved, removing the index arithmetic that made
      this possible to get wrong at all, rather than special-casing the
      one input where it showed up. `kanban-board.tsx` (Phase 2, already
      closed) shares the identical index-based pattern and the same
      theoretical exposure — out of scope for this fix (not part of this
      stage's review, and Phase 2 is closed), noted here rather than
      silently left for someone to rediscover.

      Added two regression tests: the general "first card dragged past
      others" case (pinning the still-correct 15, matching prior
      behavior) and the sharp immediate-successor case (pinning 9, where
      the old code would have computed 5 from the dragged card's own
      stale position — verified by reverting locally and confirming the
      old value before writing the fix, not assumed).

      Frontend: 48 tests across 14 files (was 46). `make check` green end
      to end (no OpenAPI diff — frontend-only change).
- [x] Stage 9 — Security matrices extended.

      **Verified against actual code before doing any work, per this
      session's established discipline, rather than trusting the plan's
      own Stage 9 text at face value** — and most of what it describes was
      already done: `make_client`/`make_lead` factories existed since
      Stages 2-3, and `test_authz_matrix.py` already had a row for every
      CRM route (added incrementally in each stage that introduced one,
      the pattern Stage 2 discovered and every later stage followed —
      confirmed directly via `grep`, not assumed from memory). The one
      real gap: `test_isolation_matrix.py` had zero CRM rows at all.

      Added `test_crm_read_routes_isolated_across_orgs`
      (`/clients/{id}`, `/leads/{id}`, all four roles — `CLIENT_READ`/
      `LEAD_READ` are MEMBER-tier, so every role reaches the service
      layer's org-scoped lookup) and `test_crm_write_routes_isolated_
      across_orgs` (`PATCH`/`DELETE /clients/{id}`, `PATCH`/`DELETE
      /leads/{id}`, `POST /leads/{id}/convert` — MANAGER+ roles only).
      The write routes are deliberately split from the read ones, same
      reasoning `test_project_write_routes_isolated_across_orgs` already
      established for `PROJECT_DELETE`: `CLIENT_WRITE`/`LEAD_WRITE`/
      `LEAD_CONVERT` have no MEMBER-reachable path at all (RBAC.md §2's
      role-threshold-only design, no ownership-split this phase), so
      testing MEMBER there would only prove MEMBER lacks the permission,
      not prove isolation. Both mirror `_WORK_ISOLATION_ROUTES`'s exact
      shape: a fresh org pair per parametrized case, never a shared
      fixture.

      Also closed a gap the plan's own Stage 9 text didn't mention
      (written before Stage 4/8 existed): neither `GET /api/v1/pipeline`
      nor `GET /api/v1/leads/stats` had an explicit org-scoping test.
      `/leads/stats` already had one from Stage 8
      (`test_stats_is_org_scoped`); added `test_pipeline_is_org_scoped` to
      `test_pipeline.py`, mirroring `test_activity_feed.py`'s own
      `test_activity_feed_is_org_scoped` — both are org-wide aggregates
      with no per-resource 404 concept, so "never leaks another org's
      data" is the right property to assert, not a 404 check.
      `POST /api/public/contact` remains deliberately absent from both
      matrices (it's `@public`, no membership/role applies — covered by
      Stage 6's own dedicated tests, same as `/health`/`/ready`). No
      `_OWNERSHIP_SPLIT_ROUTES` entries added (Context's decision — CRM is
      role-threshold only, not re-litigated).

      671 tests passing (was 647). `make check` green end to end (no
      OpenAPI diff — test-only change).
- [x] Stage 10 — Seed script extended. `scripts/seed.py`: `_get_or_create_
      client`/`_get_or_create_lead`, matched on natural keys (client name,
      lead email) — no `ON CONFLICT` SQL, matching every existing helper.
      4 clients (MASTER_PROMPT §36's "3-5") and 10 leads ("10+"), spread
      across all 7 `LeadSource` values and all 7 `LeadStage` values (not
      just "at least one of each" by accident — verified directly by
      querying `distinct source`/`distinct stage` after a real `make seed`
      run). One `WON` lead (Farah Nasser) carries a real
      `converted_client_id`; one `LOST` lead (Grace Liu) carries a real
      `lost_reason`. `_SeedProject` gained an optional `client_name`
      field; `_get_or_create_project` now backfills `client_id` on an
      already-existing project (idempotent — only ever sets an unset
      link, never overwrites one) so the one Phase 2 project seeded
      before clients existed still ends up linked. "TrinolIT Website" is
      linked to "Acme Corp" — the same client Farah Nasser's WON lead
      converts to, a deliberately coherent story rather than three
      unrelated facts.

      **A real gap this stage's own plan text didn't anticipate, found by
      actually running the new code against `test_seed_idempotent.py`
      before assuming it would pass:** that file's `_isolated_seed`
      fixture monkeypatches `_SEED_USERS`/`_SEED_PROJECTS` to uniquely-
      suffixed shadow data so its tests can run `seed_module.seed()` for
      real without ever colliding with a developer's own already-seeded
      `trinolit` org — but it had no equivalent for the two new tables.
      Running the suite immediately surfaced a `KeyError` (the new client/
      lead loops looked up owners by the *unsuffixed* real email, which
      the isolated user list no longer contained) — confirmed empirically,
      not just reasoned about. Extended `_isolated_seed` to also produce
      suffixed shadow `_SEED_CLIENTS`/`_SEED_LEADS` (translating every
      `owner_email`/`assigned_to_email`/`converted_client_name` through
      the same translation tables the existing project-shadowing already
      built), and extended `_SeedSnapshot`/`_snapshot`/
      `_cleanup_rows_created_since` to track and clean up clients and
      leads the identical per-entity, existed-before-this-run way every
      other entity already works. FK order matters here in a way it
      didn't before: leads and projects (both may reference a client) are
      now deleted before clients, and clients (which reference a
      membership via `owner_id`) before memberships — the same class of
      ordering bug this file's own history already document for
      projects/memberships, now extended to the two new entities.
      Verified empirically: reran the extended idempotency tests five
      times back to back and confirmed real row counts (queried directly
      via `asyncpg`, not just the test's own assertions) were bit-for-bit
      identical before and after.

      **A real, unrelated finding surfaced while doing that verification,
      fixed here rather than left for a later stage to stumble on:**
      Stage 8's manual Playwright walkthrough had left real rows behind
      in this same local dev database — leads/clients/projects named
      "Playwright Lead ...", "Drag Check ...", "Kanban Check ..." — never
      cleaned up after that session's browser-based verification. Found
      by comparing an actual `make seed` run's row counts against what
      Stage 10's own seed data should produce and noticing a mismatch,
      not by inspection alone. Removed those specific rows (matched by
      exact name, in FK-safe order: `activity_events` via the migrator
      role first, since `trinol_app` has no delete grant there, then
      `lead_stage_events`/`tasks`/`project_members`, then `projects`/
      `leads`, then `clients`) — confirmed via direct query that the
      `trinolit` org's data now exactly matches what this stage's own
      seed script produces, nothing extra, nothing missing.

      Manually verified against the real dev database, not just the test
      suite: ran `make seed` twice — row counts (clients/leads/projects/
      tasks/memberships/project_members) identical after the second run;
      queried `distinct source`/`distinct stage` directly, confirming all
      7 values of each are present; confirmed the WON lead's
      `converted_client_id` and the linked project's `client_id` both
      resolve to the same "Acme Corp" client row.

      671 tests passing (unchanged — this stage extends existing seed-
      idempotency tests rather than adding new ones to the count). `make
      check` green end to end (no OpenAPI diff — no route/schema changes
      this stage).
- [x] Stage 11 — E2E extension, the final stage of this phase.
      MASTER_PROMPT §37's eight E2E flows: Phase 2's `smoke.spec.ts`
      already covers login/create project/create task/move task; this
      stage adds the three remaining CRM ones — create lead, convert
      lead, create client (create invoice is Phase 5, not built yet).
      New `apps/web/e2e/crm.spec.ts` rather than growing
      `smoke.spec.ts`'s own single test further — CRM is a distinct
      chapter, and `smoke.spec.ts`'s own docstring already names this
      split ("a sibling `crm.spec.ts` if the single-spec-file convention
      gets unwieldy") as the acceptable option, confirmed directly rather
      than assumed. Two tests: one chains create-lead → convert-lead
      (converting redirects straight to the new project, the natural next
      stop and proof the conversion actually created a client + project,
      not just flipped the lead's stage — mirrors ROADMAP.md's own Phase
      3 exit criteria); the other creates a client directly via the
      Clients page's own form, since MASTER_PROMPT lists "create client"
      as its own flow, not merely an observed side effect of conversion.

      **Manually run against a real stack, not just written and assumed
      to pass** (TESTING.md §5's own Proof criterion: "`pnpm exec
      playwright test` green locally against `make dev`'s seeded stack").
      Docker wasn't available in this environment, so — same approach
      already used for Stage 8's manual verification and this same
      stage's own prerequisites — ran the API host-side (`uv run
      uvicorn`) and the web app via `pnpm dev`, both pointed at the same
      Postgres the automated suite uses, with `E2E_TEST_MODE`/
      `NEXT_PUBLIC_E2E_TEST_MODE` set and `make seed` already run. First
      attempt failed at the very first `expect(page).toHaveURL(/\/
      dashboard$/)` — traced directly (a `curl` against the session-
      exchange endpoint) to a real oversight: only the frontend's
      `NEXT_PUBLIC_E2E_TEST_MODE` had been set this time, not the
      backend's own `E2E_TEST_MODE` — fixed and reran clean. Both new
      tests pass, and — run together with the existing `smoke.spec.ts` —
      all three E2E tests pass as one suite; reran the full three-test
      suite twice more to rule out flakiness before treating it as done.

      Found, while doing that verification, real leftover rows in the
      local dev database from these same Playwright runs (multiple
      "Playwright Lead ..."/"Playwright Client ..."/"Playwright Smoke
      ..." leads/clients/projects/tasks, from re-running the suite
      several times while getting the environment right) — cleaned them
      up immediately in this same turn, FK-safe (`activity_events` via
      the migrator role first, then `lead_stage_events`/`project_members`/
      task-children, then projects/leads/clients/tasks themselves),
      confirmed directly afterward that the `trinolit` org's data was back
      to exactly this phase's own seed output (4 clients, 10 leads, 2
      projects, 10 tasks) — applying the lesson Stage 10 itself had to
      learn the hard way, this time in the same session rather than
      leaving it for a later one to trip over.

      No CI workflow change — TESTING.md §6 already scopes Playwright to
      main/release-candidate runs, not every PR, and nothing about that
      scoping changes for CRM's three additional flows.

      671 backend tests unchanged (frontend-only stage). 3/3 Playwright
      tests passing locally. `make check` green end to end (no OpenAPI
      diff — no backend changes this stage).

## Phase 4 — Meetings + Calendar

Status: **APPROVED by Codex.** All 9 stages complete and independently
reviewed; the final Phase 4 audit found no P0/P1 findings. Planned via a
dedicated plan-mode session (mirroring how Phase 3 itself started); plan
file: `reactive-dreaming-lantern.md`.

DATABASE.md §3 (lines 184-201) already fully specified the `meetings`,
`meeting_participants`, `meeting_decisions`, `meeting_actions` tables;
ARCHITECTURE.md §3 already pinned the module boundary (`meetings → work/crm`
is allowed, the mirror of Phase 3's `crm` restriction; the one cross-module
write is `MeetingAction → Task` in `meetings.services.promote_action`).
RBAC.md, unlike Phase 3, had only one thin matrix row and one enforcement
line for meetings — several real decisions were made explicitly during
planning rather than invented mid-stage:

- **Meeting reminder emails are skipped entirely this phase** (user
  decision): a reminder needs a time-triggered send, and ADR-0010 rules out
  any Redis/background-worker mechanism in V1. Treated like Google
  Calendar's own "not justified until asked" deferral (ADR-0012) — no
  template, no trigger.
- **No in-app calendar-grid view this phase** (user decision): no spec doc
  names one — MASTER_PROMPT.md has no `## Calendar` section, and
  ROADMAP.md's own checklist below never listed a calendar-grid page. The
  phase name's "Calendar" half refers to the deferred Google Calendar
  integration bullet.
- **Visibility vs. edit are different rules**: RBAC.md's one enforcement
  line only covered edit (creator or MANAGER+). Visibility needed its own
  rule since meetings, like projects, are multi-person resources: view =
  MANAGER+ OR creator OR a `meeting_participants` row for the actor (mirrors
  `ensure_project_visible`); edit/delete = MANAGER+ OR creator only. One new
  permission, `MEETING_READ` (MEMBER-tier), added to gate view-route
  reachability alongside the pre-existing `MEETING_WRITE_OWN`.
- **Sub-resources (decisions, actions) inherit the meeting's own edit
  rule**, not an author-only rule — neither has `edited_at` in DATABASE.md's
  spec and neither is discourse, so they follow task checklist items/
  attachments' precedent ("no author concept here"), not task comments'
  independent author-only exception. Participants may update their own
  `response` regardless of the edit rule.
- **`meeting_decisions.decided_by`/`meeting_actions.owner_id`'s ON DELETE
  action fills a real gap in DATABASE.md §5.2** (its RESTRICT-nullable-actor
  row didn't list these two) — treated identically to every other nullable
  "person who did X" column (RESTRICT to `memberships`).

Exit criteria: a MEMBER can create a meeting, add participants, record
decisions and action items, and see meetings they're invited to; only the
creator or a MANAGER+ can edit/delete the meeting; promoting an action to a
task is one transaction, provably atomic, and rejects double-promotion;
deleting a meeting hard-deletes it (ADR-0011 — meetings are not among the
four soft-deleted entities) with a same-transaction audit event.

- [x] Stage 1 — `meetings` module schema. `modules/meetings/models.py`:
      `MeetingParticipantResponse` (new StrEnum — DATABASE.md leaves
      `response` undefined — `PENDING`/`ACCEPTED`/`DECLINED`/`TENTATIVE`),
      `Meeting`, `MeetingParticipant`, `MeetingDecision`, `MeetingAction` —
      exact columns/constraints from DATABASE.md §3, following `Project`/
      `Task`'s template: `OrgScoped` mixin, `uq_meetings_org_id`,
      `ck_meeting_times (ends_at > starts_at)`, `ck_meeting_participant_
      identity` (exactly one of `user_id`/`external_email`), composite FKs
      to `memberships(organization_id, user_id)` for every person
      reference, `RESTRICT` throughout (§5.2 — deactivation, not deletion,
      is the supported path). `Meeting` gets both `created_at` and
      `updated_at` (DATABASE.md's "timestamps," plural, for the meetings
      row itself); its three sub-resources only get `created_at` (no
      `edited_at`/`updated_at` in their spec — append-only in spirit, not
      discourse). No `archived_at` anywhere (ADR-0011: meetings are
      hard-deleted). `migrations/versions/0006_meetings_schema.py`: new
      tables, hand-written raw SQL matching `0003`/`0004`/`0005`'s exact
      style. `core/authz/permissions.py`: added `MEETING_READ`
      (`MEMBER`-tier) alongside the pre-existing `MEETING_WRITE_OWN`.
      `RBAC.md`: added the "Meetings: view" matrix row and documented the
      visibility/edit split, the sub-resource inheritance rule, and the
      participant-own-response exception in §3 — the same kind of
      gap-fill RBAC.md already carries for `PROJECT_MEMBER_WRITE`.

      **A real finding, verified empirically before fixing, not assumed
      from the plan.** `alembic check` failed after the migration was
      written and applied — not because the migration was wrong, but
      because `migrations/env.py` (unlike `tests/security/
      test_schema_integrity.py`, which the plan already flagged as needing
      the same treatment) never imported `trinol.modules.meetings.models`
      for its side effect of registering tables on `Base.metadata`.
      Alembic's autogenerate compare saw the four new tables in the live
      database but not in the target metadata, and concluded they should
      be dropped — the exact *shape* of import-completeness bug Phase 3
      Stage 1 already found once in the test file, now found in the
      migration environment itself, a file that bug never touched before
      because CRM's own equivalent fix only ever added the import to the
      test file. Fixed by adding the same explicit import to `migrations/
      env.py`, mirroring its own existing discipline for `crm`/`work`.
      Verified directly: `alembic check` failed with "New upgrade
      operations detected" (four `remove_table`s) before the fix, and
      reported "No new upgrade operations detected" after.

      Verified the schema-integrity tests are not passing vacuously the
      same way Phase 3 Stage 1 did: deliberately added a real single-
      column FK (`meeting_decisions.client_id_test -> clients.id`, a
      genuinely valid target since `clients.id` has its own single-column
      primary key) via `psql` against the migrator role, confirmed
      `test_every_fk_between_org_scoped_tables_is_composite` failed on it
      with the expected violation message, then dropped the column and
      constraint and confirmed the suite was clean again.

      `alembic upgrade head` / `downgrade -1` / `upgrade head` clean;
      `alembic check` clean; full suite (671 tests, unchanged — schema-only
      stage, no new test cases beyond the schema-integrity import and the
      new factories), ruff, ruff format, mypy all green.

- [x] Stage 2 — Meeting CRUD. `modules/meetings/schemas.py`:
      `MeetingCreateRequest`/`MeetingUpdateRequest`/`MeetingResponse`/
      `MeetingListResponse`. `client_id`/`project_id` are plain UUIDs, not
      embedded `ClientResponse`/`ProjectResponse` objects — deliberate
      deviation from the plan's own draft text, matching the existing
      precedent every other cross-module reference field in this codebase
      already follows (`ProjectResponse.client_id`, `LeadResponse.
      converted_client_id`); embedding would be new scope this phase
      doesn't need. `modules/meetings/services/meeting_service.py`:
      `ensure_meeting_visible` (MANAGER+ OR creator OR a
      `meeting_participants` row for the actor — direct copy of
      `ensure_project_visible`'s shape), `can_write_meeting` (MANAGER+ OR
      creator only — RBAC.md's literal rule), `create_meeting` (everyone
      may create; validates `client_id`/`project_id` against the org via
      `crm.services.client_service.get_client_in_org`/`work.services.
      project_service.get_project_in_org` — the `meetings → work/crm`
      import direction ARCHITECTURE.md §3 explicitly allows; `record(...,
      audit=False)` wired inline, Phase 2's pattern rather than Phase 3's
      later-stage retrofit), `list_meetings` (visibility-filtered, same
      shape as `list_projects`), `get_meeting`, `update_meeting` (partial
      update; cross-field `starts_at`/`ends_at` consistency checked
      against the persisted row when only one is in the request body, same
      split `update_project` uses for `start_date`/`deadline`),
      `delete_meeting` (hard delete per ADR-0011 + same-transaction
      `is_audit=true` event, mirrors `delete_task` exactly — no
      `file_objects` cleanup needed, meetings have no attachments this
      phase). `modules/meetings/routes/meetings.py`: the 5 CRUD routes,
      registered in `main.py`.

      `tests/integration/test_meetings.py` (25 tests): full CRUD
      round-trip; every role can create; visibility (creator/participant/
      MANAGER+ can `GET`, an unrelated MEMBER 403s); edit (creator/
      MANAGER+ can `PATCH`/`DELETE`, a participant who isn't the creator
      cannot); partial-update cross-field validation against the
      persisted row; `meeting.created`/`meeting.deleted` land in the
      correct feed/audit table (`is_audit=false`/`true` respectively,
      checked directly via `platform.activity.list_feed`/`list_audit` —
      there's no HTTP endpoint for the audit log yet, so this can't be
      asserted through the API the way the plan's own draft phrasing
      implied); cross-org `client_id`/`project_id` rejected with 404;
      cross-org meeting access 404s.

      `tests/security/test_authz_matrix.py`: plain rows for `POST`/`GET
      (list) /meetings` (both role-threshold-only, no ownership split); a
      new `test_meeting_routes_enforce_ownership_split` for `GET`/`PATCH`/
      `DELETE /meetings/{id}` — the first ownership-split test in this
      matrix where a single role (`participant`) has to pass one method
      (`GET`) and fail the other two (`PATCH`/`DELETE`), unlike every
      existing ownership-split test where an access level is uniformly
      allowed or denied across all its methods.
      `tests/security/test_isolation_matrix.py`: a new
      `_MEETING_ISOLATION_ROUTES`/`test_meeting_routes_isolated_across_orgs`
      pair — every role tests cross-org 404 (unlike CRM's write routes,
      which only test MANAGER+/ADMIN/OWNER since `LEAD_WRITE`/
      `CLIENT_WRITE` have no MEMBER-reachable path at all; meetings' edit
      routes ARE MEMBER-reachable via `MEETING_WRITE_OWN`, so every role
      genuinely needs the isolation check, the same shape
      `_WORK_ISOLATION_ROUTES` already uses for task routes).

      65 new backend tests (671 → 736); ruff, ruff format, mypy, `make
      openapi` (frontend `types.gen.ts` diff, not yet committed at
      verification time — expected, resolved by this stage's own commit)
      all green. Frontend `pnpm typecheck`/`pnpm test`/`pnpm build`
      unaffected (no frontend changes this stage — that's Stage 7).

- [x] Stage 3 — Participants. `modules/meetings/services/
      meeting_participant_service.py` (own file, mirroring
      `project_member_service.py`'s file-split precedent): `add_participant`
      (gated by `can_write_meeting` — creator or MANAGER+, no new
      permission needed; accepts exactly one of `user_id`/`external_email`,
      validated in `MeetingParticipantAddRequest` mirroring
      `ck_meeting_participant_identity`; `user_id` validated against an
      active membership via `get_active_membership_by_user`; duplicate
      participant rejected with 409), `list_meeting_participants` (gated
      by `ensure_meeting_visible` — same rule as the parent meeting's own
      `GET`), `remove_participant` (`can_write_meeting`),
      `update_participant_response` (Stage 1's own decision: the
      participant's own RSVP is theirs to change regardless of
      `can_write_meeting` — implemented as `participant.user_id ==
      actor.user_id OR can_write_meeting(actor, meeting)`; no activity
      event, since changing your own RSVP doesn't change who can see the
      meeting — not guard 6's `is_audit=true` case, and not ordinary feed
      content either). `add_participant`/`remove_participant` record
      `meeting_participant.added`/`removed` with `audit=True` (RBAC.md §3:
      changes meeting visibility, same reasoning as
      `project_member.added`/`removed`).

      `modules/meetings/schemas.py`: `MeetingParticipantAddRequest`,
      `MeetingParticipantResponseUpdateRequest`, `MeetingParticipantResponse`
      (the API schema — aliased the model's own
      `MeetingParticipantResponse` enum import to `ParticipantInviteStatus`
      to avoid a name collision, since that enum name describes an RSVP
      status, not a response schema, a naming overlap baked in at Stage 1),
      `MeetingParticipantListResponse`. 4 new routes in
      `routes/meetings.py` (`POST`/`GET /meetings/{id}/participants`,
      `PATCH`/`DELETE /meetings/{id}/participants/{participant_id}`).

      `tests/integration/test_meeting_participants.py` (18 tests): both
      identity paths (`user_id`, `external_email`); the exactly-one-of
      validation (422 on both or neither); duplicate rejection (409);
      creator/MANAGER+ can manage the roster, a non-creator MEMBER cannot;
      adding a participant is proven to actually grant them visibility
      (`GET` on the meeting itself flips 403→200 after being added, not
      just that the add call succeeded); a participant can update only
      their own response, not someone else's; the creator/MANAGER+ can
      also set a participant's response on their behalf; `is_audit=true`
      for add, absent from the ordinary feed; cross-org 404.

      `tests/security/test_authz_matrix.py`: all 4 new routes are
      ownership-split (none is a plain role-threshold row) — added to
      `_OWNERSHIP_SPLIT_ROUTES` and covered by two new dedicated tests:
      `test_meeting_participant_roster_routes_enforce_ownership_split`
      (`POST`/`GET`/`DELETE`, same "participant passes GET only" asymmetry
      Stage 2's own meeting-level test already established) and
      `test_update_participant_response_route_enforces_self_or_ownership_split`
      (`PATCH`'s own three-way split: self, creator, or MANAGER+ — distinct
      from every other ownership-split shape in this file, since even an
      "unrelated participant" of the *meeting* is still forbidden here
      unless they're the specific participant row being updated).
      `tests/security/test_isolation_matrix.py`: `_MEETING_PARTICIPANT_
      ISOLATION_ROUTES`/`test_meeting_participant_routes_isolated_across_
      orgs` — every role, same reasoning Stage 2's own meeting isolation
      table used (`MEETING_READ`/`MEETING_WRITE_OWN` are both MEMBER-tier
      reachable, unlike CRM's MANAGER+-only writes).

      58 new backend tests (736 → 794); ruff, ruff format, mypy, `make
      openapi` all green (frontend unaffected — no changes this stage).

      **Codex P1: `add_participant`'s duplicate check was a bare
      check-then-insert with no lock and no matching DB uniqueness
      constraint** (unlike `ProjectMember`'s real
      `UniqueConstraint("project_id", "user_id")`) — two concurrent adds
      for the same `user_id`/`external_email` could both pass the "no
      existing participant" check and both insert, since
      `meeting_participants` has no partial unique index for either
      identity path and the meeting row wasn't locked. Fixed by giving
      `get_meeting_in_org` the same `for_update: bool = False` parameter
      `lead_service.get_lead_in_org` already has, and calling it with
      `for_update=True` in `add_participant` — the second concurrent
      request blocks on the meeting row's lock until the first commits,
      then its own duplicate check sees the just-inserted row and 409s,
      same shape and reasoning as `lead_conversion_service.convert_lead`'s
      own fix for the identical bug class (Phase 3 Stage 5). Chose the
      row-lock fix over a DB-level partial unique index (Codex's other
      suggested option) since this codebase already has an established,
      reviewed idiom for exactly this race shape and a schema change would
      mean a new migration for an already-closed Stage 1 table; no new
      migration needed.

      Two new regression tests in `test_meeting_participants.py`
      (`test_concurrent_add_by_user_id_only_one_succeeds`,
      `test_concurrent_add_by_external_email_only_one_succeeds` — both
      identity paths, since the duplicate check queries a different
      column for each), mirroring `test_lead_conversion.py`'s own
      concurrent-conversion test exactly: two independent DB sessions,
      `asyncio.gather`, real commits outside the test-fixture rollback
      boundary. Verified the fix is real, not vacuous: reverted
      `for_update=True` temporarily and confirmed both new tests fail
      consistently (3/3 runs, both duplicate rows actually created each
      time), then restored the fix and confirmed both pass consistently
      (3/3 runs) before treating it as done.

      796 backend tests (794 → 796, +2 race tests); ruff, ruff format,
      mypy, `make openapi` (no diff — service-layer fix only, no
      route/schema change) all green.

      **Codex P1 (re-review): both new race tests claimed explicit cleanup
      but only deleted `activity_events`** — they left their organizations,
      users, memberships, meetings, and participant rows permanently in
      the shared database, the exact trap `test_lead_conversion.py`'s own
      race test had already solved but my copy didn't fully follow (I'd
      read only part of that function on the first pass and missed its
      second, FK-ordered cleanup block). Fixed by adding the same
      FK-ordered cleanup pattern: `MeetingParticipant` (child of
      `Meeting`) before `Meeting`, before `Membership`, before `User`(s),
      before `Organization` — mirrors the composite-FK RESTRICT chain in
      DATABASE.md §5.1/§5.2, `ActivityEvent` still via the migrator role
      separately (ADR-0006's REVOKE). Verified directly, not assumed: a
      database audit turned up 20 orphaned organizations (and their 26
      participant rows, 30 memberships, 30 users) left behind by my own
      earlier manual `pytest -k concurrent` re-runs during the first P1
      fix — cleaned up by hand via the migrator role in FK order, then
      re-ran the two tests and confirmed zero related rows remain
      afterward (`meeting_participants`/`meetings`/`race-*` users all at
      0). Also found and cleaned two unrelated pre-existing orphaned
      organizations from a different, already-approved test file's own
      race test (a stray `activity_events` row each, blocking their
      `Organization` delete) — out of this stage's scope, not
      investigated further, just tidied up while auditing.

      796 backend tests unchanged (cleanup-only fix, no new test cases);
      ruff, ruff format, mypy all green.

- [x] Stage 4 — Decisions + Actions. `modules/meetings/services/
      meeting_decision_service.py` (own file, mirroring
      `task_checklist_service.py`'s file-split precedent):
      `create_decision`/`list_decisions`/`delete_decision`, all gated by
      `can_write_meeting` (creator or MANAGER+ — no independent
      permission, no author-only rule; there's no author concept on a
      decision to hang comments' own rule on). No `update_decision` —
      append-only in spirit, no `edited_at` in DATABASE.md's spec.
      `modules/meetings/services/meeting_action_service.py`: same shape
      plus `update_action` (`owner_id`/`description`/`due_date` only —
      `task_id` is never in `MeetingActionUpdateRequest` at all, not just
      excluded at the service layer, so there's no path by which a client
      could set it; it's stamped exactly once by `promote_action`,
      Stage 5). `owner_id` validated against an active membership via
      `get_active_membership_by_user` on both create and update.

      **A real decision verified against ADR-0011's actual text before
      implementing, not assumed from the plan's own draft.** The plan
      said decision/action creation should record ordinary feed content
      (`meeting_decision.created`/`meeting_action.created`, `is_audit=
      false`) but was silent on delete. Re-read ADR-0011 directly: "Every
      thing else is a hard delete, with the deletion recorded as an audit
      event" — a blanket rule, not limited to visibility-relevant deletes
      (confirmed by reading `delete_checklist_item`'s own docstring, which
      cites the same ADR for the identical reasoning). So
      `delete_decision`/`delete_action` both record `audit=True` events,
      matching `delete_checklist_item`/`delete_comment`'s precedent
      exactly — a gap the plan's draft text didn't spell out, caught by
      re-reading the source ADR rather than trusting the summary.

      `modules/meetings/schemas.py`: `MeetingDecisionCreateRequest`/
      `MeetingDecisionResponse`/`MeetingDecisionListResponse`,
      `MeetingActionCreateRequest`/`MeetingActionUpdateRequest`/
      `MeetingActionResponse`/`MeetingActionListResponse`. 7 new routes in
      `routes/meetings.py` (`POST`/`GET /meetings/{id}/decisions`,
      `DELETE /meetings/{id}/decisions/{decision_id}`, `POST`/`GET
      /meetings/{id}/actions`, `PATCH`/`DELETE
      /meetings/{id}/actions/{action_id}`).

      `tests/integration/test_meeting_decisions.py` (11 tests) and
      `test_meeting_actions.py` (17 tests): creator/MANAGER+ can
      create/delete (and, for actions, update), a non-creator MEMBER
      cannot; `owner_id` rejected if it's not an active membership in the
      org; `task_id` proven to have no effect even when sent in a PATCH
      body (Pydantic silently ignores an unmodeled field, so this checks
      the actual response, not just that the schema "doesn't have" the
      field); create records a feed event, delete records an audit event
      (`is_audit=false`/`true` respectively, checked via
      `platform.activity.list_feed`/`list_audit` directly); cross-org 404.

      `tests/security/test_authz_matrix.py`: all 7 new routes added to
      `_OWNERSHIP_SPLIT_ROUTES` and covered by one new dedicated
      parametrized test,
      `test_meeting_decision_and_action_routes_enforce_ownership_split`,
      reusing the same "participant passes GET only" asymmetry established
      for the participant roster routes — unlike the participant
      response-update route, actions' own `PATCH` has no self-exception,
      so it fits the same shape as `POST`/`DELETE` here.
      `tests/security/test_isolation_matrix.py`:
      `_MEETING_CONTENT_ISOLATION_ROUTES`/
      `test_meeting_content_routes_isolated_across_orgs` — every role,
      same reasoning the participant/meeting isolation tables already
      established.

      94 new backend tests (796 → 890); ruff, ruff format, mypy, `make
      openapi` all green (frontend unaffected — no changes this stage).

- [x] Stage 5 — `promote_action` (the one cross-module write). `modules/
      meetings/services/meeting_action_service.py`: `promote_action` —
      one transaction, gated by `can_write_meeting` (creator or MANAGER+,
      no participant exception, same shape as create/update/delete).
      Critical, confirmed by direct read of `task_service.create_task`
      before writing a line of this function: `create_task` ends with its
      own `await db.commit()`, so calling it here would silently break
      the "one transaction" rule ARCHITECTURE.md §3 requires. Inlines a
      bare `Task(...)` construction instead, exactly like
      `lead_conversion_service.convert_lead` inlines `Project(...)`/
      `Client(...)` rather than calling `project_service.create_project()`.
      Field mapping: `description → title`, `owner_id → assignee_id`
      (re-validated against an active membership at promotion time, not
      just trusted from creation — the owner could have been deactivated
      since), `due_date → due_date`, `meeting.project_id → project_id`
      (nullable-safe), `created_by = actor.user_id`, `status = TODO`,
      `priority = MEDIUM`. `board_position` deliberately left unset (not
      `None` — omitted entirely) so the DB's own `server_default` fires,
      matching how `create_task` itself only sets it when a caller
      explicitly passes one.

      Row-lock guard: `get_meeting_action_in_org` gained the same
      `for_update: bool = False` parameter `lead_service.get_lead_in_org`
      already has; `promote_action` calls it with `for_update=True`
      before checking `action.task_id is not None` — the second of two
      concurrent promote calls blocks until the first commits, then sees
      `task_id` already set and 409s, same shape and reasoning as
      `convert_lead`'s own fix for the identical bug class (Phase 3
      Stage 5). `meeting_action.promoted` and `task.created` are both
      recorded as ordinary feed content (`is_audit=false`) inside the one
      transaction, then a single `db.commit()`. Route:
      `POST /meetings/{id}/actions/{action_id}/promote`, returns the
      created `Task` (reusing `work.routes.tasks.task_to_response` and
      `TaskResponse` directly — `meetings → work` schema/route reuse is
      explicitly allowed, same as `work`'s own existing imports from `crm`).

      `tests/integration/test_meeting_action_promotion.py` (8 tests):
      happy path; field-mapping correctness (owner/due_date/meeting's own
      project all land on the created task); both activity events land as
      feed content; a second promotion attempt 409s without creating a
      second task; non-creator MEMBER 403s; cross-org 404;
      **an atomicity regression test** — monkeypatches the second
      `record()` call (`task.created`, which runs after the Task is
      flushed) to raise, confirms `promote_action` raises, then confirms
      after rollback that no `Task` row exists and `action.task_id` was
      never persisted; **a concurrency regression test** — two
      independent DB sessions, `asyncio.gather`, real commits outside the
      test-fixture rollback boundary, mirroring `test_lead_conversion.py`'s
      own concurrent-conversion test exactly, proving Postgres actually
      serializes the two attempts via the action row's `FOR UPDATE` lock,
      not just that they happen not to race within one shared transaction.

      Verified both regression tests are real, not vacuous, before
      trusting them: temporarily added a premature `db.commit()` right
      after the flush and confirmed the atomicity test failed (the Task
      survived); temporarily removed `for_update=True` and confirmed the
      concurrency test failed consistently (3/3 runs, two Tasks created
      each time) — then restored both fixes and confirmed both tests pass
      consistently (3/3 runs each) before treating them as done. Found
      and fixed three unrelated test bugs surfaced along the way: a
      missing `X-CSRF-Token` header on one `POST` test (was asserting 404
      but actually got 403 from the CSRF/origin check firing first), a
      `MissingGreenlet` crash from accessing ORM object attributes after
      `db_session.rollback()` (which always expires attributes regardless
      of `expire_on_commit`) — fixed by capturing plain-value ids before
      the rollback, and an FK-ordering bug in the race test's own cleanup
      (deleted `Task` before `MeetingAction`, which still referenced it —
      swapped the order).

      `tests/security/test_authz_matrix.py`/`test_isolation_matrix.py`:
      the `/promote` route added to the existing decisions/actions
      ownership-split and isolation tables (same edit-only shape, no new
      test needed). Final confirmation: `grep -rl "from trinol.modules.
      meetings" apps/api/src/trinol/modules/work apps/api/src/trinol/
      modules/crm` returns nothing — neither module imports `meetings`.

      18 new backend tests (890 → 908); ruff, ruff format, mypy, `make
      openapi` all green (frontend unaffected — no changes this stage).

- [x] Stage 6 — Activity feed wiring review. A verification pass, not
      first-time authoring: every meetings event was already wired inline
      per-stage (Stages 2-5, Phase 2's pattern rather than Phase 3's
      deferred-then-retrofitted one), so this stage confirms correctness
      centrally rather than adding new production code.

      Found a real gap in test coverage while doing this: unlike CRM/work,
      no meetings event had a dedicated assertion in
      `tests/integration/test_activity_writer.py` — the file that, by
      established convention (confirmed by checking `test_clients.py`/
      `test_leads.py`/`test_projects.py` directly: none of them have their
      own `list_feed`/`list_audit` checks), is the *sole* place activity
      events get asserted, calling services directly rather than through
      the HTTP client. Added 9 tests there, one per event: `meeting.
      created`/`meeting.deleted` (feed/audit), `meeting_participant.
      added`/`removed` (both audit — confirmed the participant-response
      self-service update writes no event at all, neither table),
      `meeting_decision.created`/`deleted`, `meeting_action.created`/
      `deleted` (feed/audit each), and `meeting_action.promoted` +
      `task.created` together (both feed, in the one promote_action
      transaction). Every `is_audit` flag confirmed to match what Stages
      2-5 actually implemented — no mismatches found.

      One real test bug caught while writing these: the first draft of
      `test_delete_decision_writes_an_audit_event_not_feed` asserted
      `list_feed(...) == []` after calling `create_decision` then
      `delete_decision` — failed immediately, because `create_decision`
      itself legitimately writes a `meeting_decision.created` feed row
      that delete doesn't touch. Fixed by using the `make_meeting_decision`
      factory instead of the `create_decision` service call to seed the
      row, matching `test_delete_action_writes_an_audit_event_not_feed`'s
      own already-correct choice (`make_meeting_action`, not
      `create_action`) for the identical reason.

      Confirmed no gap in `tests/integration/test_activity_feed.py`: that
      file tests the `/api/v1/activity` route's generic mechanism (items+
      total shape, audit-event exclusion, org-scoping) using project/task
      as representative content, the same way it never needed CRM-specific
      rows either — the property is already proven module-agnostic via the
      existing `project_member.added`/`removed` audit-exclusion case.

      9 new backend tests (908 → 917); ruff, ruff format, mypy, `make
      openapi` (no diff — test-only stage) all green.

- [x] Stage 7 — Frontend: Meetings pages, nav. First frontend stage this
      phase — everything through Stage 6 was backend-only. Explored the
      exact existing Leads/Clients patterns before writing anything
      (`leads/page.tsx`'s four-state list + inline create form,
      `clients/[id]/page.tsx`'s tab strip with empty-state-only tabs,
      `role-context.tsx`, `lib/api/client.ts`'s wrapper shape), then
      independently re-verified the highest-stakes claims directly rather
      than trusting a research pass at face value: the sidebar's exact
      `NAV_GROUPS` structure, `client.ts`'s Lead section, `role-context.tsx`
      in full, and — the most surprising claim — `types.gen.ts`'s mangled
      participant-response type name (confirmed by direct grep:
      `trinol__modules__meetings__schemas__MeetingParticipantResponse` for
      the response schema, `trinol__modules__meetings__models__
      MeetingParticipantResponse` for the RSVP enum, `MeetingParticipant
      Response-Input` for the request-side enum literal — three different
      names for what the backend calls by only two, since
      openapi-typescript had to disambiguate the schema/model name
      collision Stage 3 introduced).

      `lib/api/client.ts`: `Meeting`/`MeetingList`/`MeetingCreateRequest`/
      `MeetingUpdateRequest` types and `fetchMeetings`/`fetchMeeting`/
      `createMeeting`/`updateMeeting`/`deleteMeeting`, plus participant/
      decision/action sub-resource wrappers and `promoteMeetingAction`
      (typed to return `Task`, not a meeting-action type — `promote_
      action`'s own `response_model` is `TaskResponse`, confirmed directly
      in `types.gen.ts` before writing the wrapper, not assumed from the
      name).

      `app/(app)/meetings/page.tsx`: four-state list (loading/error/empty/
      populated) mirroring `leads/page.tsx` exactly, plus an inline create
      form (title, start/end `datetime-local` inputs converted to UTC ISO
      via `new Date(...).toISOString()` — the standard, no custom
      timezone handling needed). Unlike Leads/Clients, the "New meeting"
      control is never role-gated — RBAC.md §2's "Meetings: create/edit
      own" is granted to every role, confirmed directly rather than
      reusing `useCanManageCrm` (which is CRM-specific by its own
      docstring) or inventing a new hook.

      `app/(app)/meetings/[id]/page.tsx`: the five MASTER_PROMPT §14 tabs.
      Agenda and Notes are read-only, rendering the meeting's own
      `description`/`notes` fields directly — Agenda has no backing field
      anywhere in DATABASE.md (confirmed during planning), so this is the
      closest honest fit, not a query. Attendees: list + add (team-member
      picker via the existing `fetchTeamMembers`, or a plain external-email
      input — the two identity paths `MeetingParticipantAddRequest` itself
      models) + remove + per-row RSVP `<select>`. Decisions: list + create
      + delete, no edit (append-only in spirit, matches the backend's own
      Stage 4 decision). Action Items: list + create + delete + a
      "Promote to task" button that becomes a "View task" link once
      `task_id` is set. No edit UI for the meeting's own fields
      (title/description/notes/etc.) or for action items — the plan's own
      exit criteria never asked for one. `ponytail: read-only meeting
      fields and action items, add edit forms when requested.` No
      client-side permission pre-check anywhere (confirmed this is the
      established pattern by reading `projects/[id]/page.tsx`'s
      `handleMoveTask` directly) — every mutation attempts the call and
      surfaces whatever `ApiError` comes back through a local `role="alert"`
      message, same shape as every other mutation in this app.

      `components/nav/sidebar.tsx`: added `href: "/meetings"` to the
      COMPANY group's existing placeholder entry — confirmed via direct
      read that this really is the only diff between disabled-placeholder
      and live nav item (Team/Leads/Clients already prove the pattern).
      `Calendar` (WORK group) deliberately left with no `href` — no in-app
      calendar-grid view this phase (Phase 4 planning decision, ADR-0012).

      `tests/meetings.test.tsx` (5 tests) and `tests/meeting-detail.test.tsx`
      (5 tests): four-state list coverage, the always-visible create
      control (no role gating to test, unlike Leads), delete-meeting error
      handling, and one representative create-then-see-it-appear
      interaction per tab (Attendees, Decisions, and the full
      promote-then-link-to-task flow) — matching Phase 2/3's own
      representative-not-exhaustive scope for detail-page tests. Two MSW
      handlers needed a stateful call counter rather than two static
      handlers for the same route (registering a second `server.use()` for
      an already-matched path doesn't override the first the way two
      sequential `.use()` calls might suggest — MSW checks the
      most-recently-registered handler first for every request, not just
      subsequent ones). `sidebar.test.tsx`: added "Meetings is a real link"
      and "Calendar stays disabled" cases.

      **Manual browser walkthrough**, per CLAUDE.md's own requirement and
      this session's memory lesson about cleaning up such runs immediately.
      Port 8000 was occupied by the unrelated sibling "Trinol Payment"
      project exactly as a saved memory warned — confirmed via `curl .../
      openapi.json`'s `info.title` before assuming anything, then ran the
      backend/frontend on 8010/3010 instead. The bundled Playwright MCP
      browser tool itself failed (no local Chrome install, no sudo
      available to fix it non-interactively) — rather than treating that
      as "E2E blocked" (the exact mistake a saved memory lesson already
      warns against), wrote a small standalone script using this repo's
      own already-installed `@playwright/test` Chromium (the same binary
      Phase 3 Stage 11's E2E suite already uses) and drove the walkthrough
      with that instead. End to end, against the real seeded
      `founder@trinolit.com`: logged in → created a meeting → added an
      external-email attendee → recorded a decision → added an action item
      → promoted it → followed the resulting "View task" link and
      confirmed the real task page, with the correct title/status/priority,
      genuinely renders at `/tasks/{id}`. Screenshots captured at each step
      confirmed visually (sidebar's Meetings/Calendar state, the tab
      strip, the promoted action becoming a task link). Cleaned up
      immediately in the same turn: the meeting/participant/decision/
      action/task rows this walkthrough created in the real seeded
      `trinolit` organization (not a throwaway org — this hit the actual
      seed data, so cleanup was scoped to exactly these rows, not the
      whole org), the temporary `.env`/`.env.local` port and
      `E2E_TEST_MODE` overrides (reverted from a backup taken before
      editing), the scratch walkthrough script, and both dev server
      processes.

      12 new frontend tests (48 → 60); `pnpm typecheck`, `pnpm lint`,
      `pnpm exec prettier --check`, `pnpm test`, `pnpm build` all green.
      Backend unaffected (917 tests unchanged, confirmed by re-running the
      full suite) — no backend code touched this stage. `make check`
      green end to end, confirmed with a clean exit code, not just no
      visible error text.

- [x] Stage 8 — Security matrices review pass. A verification/audit pass,
      not first-time authoring: every meeting route already got its
      authz-matrix and isolation-matrix row in the same stage it was
      built (Stages 2-5), unlike Phase 3's CRM module, which deferred
      most of this to one dedicated late stage. Enumerated all 16 live
      meeting routes directly via `iter_api_routes(app)` rather than
      trusting the matrix files' own contents, then cross-checked each
      one by name against `test_authz_matrix.py`'s `_MATRIX_ROWS`/
      `_OWNERSHIP_SPLIT_ROUTES` and `test_isolation_matrix.py`'s own
      route tables — all 16 present in both (2 plain role-threshold rows
      for `POST`/`GET /meetings`, 14 ownership-split rows for everything
      addressing a specific resource). Confirmed the 2 collection-level
      routes are correctly absent from the isolation matrix, matching
      established precedent across every other module (isolation testing
      is inherently about a specific other-org resource leaking, which a
      bare collection route has none of — checked directly that CRM/work's
      own collection routes are equally absent there, not just assumed).
      Confirmed `test_escalation.py` needs no new rows: it covers only the
      org-role-assignment guards (`change_role`/`remove_member` on
      `Membership`), and meetings introduces no role-assignment surface at
      all — no route sets or changes an org `Role`.

      `test_matrix_covers_every_permission_gated_route`'s own meta-
      assertion has been enforcing this automatically every stage anyway
      (it already failed the suite once during Stage 2 planning if a row
      were missing), so this audit's clean result confirms rather than
      discovers — no gap found, nothing to fix.

      917 backend tests unchanged (audit-only stage, no new test cases,
      no production code changes); full security suite (547 tests), ruff,
      ruff format, mypy all green.

- [x] Stage 9 — Seed script + E2E, final stage. `scripts/seed.py`:
      `_get_or_create_meeting` — natural key `(organization, title,
      starts_at)`, matching MASTER_PROMPT §36's "past/upcoming meetings"
      with 2 past meetings and 1 upcoming: "Website Kickoff" (linked to
      the WEB project and Acme Corp, 3 attendees including one external
      guest, one decision, one action item promoted to a real task —
      exercising the same `MeetingAction -> Task` shape `promote_action`
      itself produces, inline-constructed here the same way every other
      entity in this script is, never through the service layer),
      "Sprint Retrospective" (internal, one declined attendee, one
      decision, one un-promoted action item), and "Client Check-in" (an
      upcoming meeting with pending attendees, deliberately no decisions/
      actions — it hasn't happened yet).

      **A real design bug caught and fixed before it ever landed.** The
      first draft gave the promoted task's title its own separately-
      authored string, distinct from the action's own `description` —
      inconsistent with `promote_action`'s actual field mapping
      (`title = action.description` verbatim), so it wouldn't have
      genuinely exercised the same shape it claimed to. Fixed by removing
      the separate string entirely (`promote: bool` instead), deriving
      the task's title from the action's own description directly — the
      only way this check can't silently drift out of sync again.

      **Fixed dates, not "today"-relative ones, and why:** meetings'
      natural key includes `starts_at`, so (unlike `next_follow_up`,
      which is written once at creation and never read back into an
      idempotency check) a value computed from `datetime.now()` at
      import time would silently produce a NEW row every time `make
      seed` runs on a different calendar day — the exact idempotency bug
      the fixed dates avoid. Documented as a deliberate, cosmetic staleness
      (`ponytail: these dates will eventually stop reading as "past"/
      "upcoming" as real time passes them — not a correctness bug`).

      `tests/unit/test_seed_idempotent.py`: extended `_isolated_seed`/
      `_SeedSnapshot`/`_cleanup_rows_created_since` to meetings
      proactively, applying Stage 10 of Phase 3's own lesson up front
      this time rather than rediscovering it reactively — and immediately
      rediscovered a *different*, genuinely new version of it anyway:
      running the extended test suite for real threw a bare `KeyError`
      (the shadow `_SEED_PROJECTS` had no matching shadow `_SEED_MEETINGS`,
      so `seed()`'s own project-code lookup missed), then, after fixing
      that, a `ForeignKeyViolationError` on `fk_tasks_org_project_projects`
      (the cleanup order deleted projects before the meetings/promoted-
      tasks that reference them — moved the whole meetings cleanup block
      to run first, since a meeting or its promoted task can reference a
      project or client the same RESTRICT way leads/clients already do).
      A third, more subtle fix: an existing assertion
      (`len(tasks) == len(project_entry.tasks)` for a project's own task
      count) broke once a meeting's promoted task could *also* legitimately
      land under that same project — fixed by filtering to each project's
      own `_SeedTask` titles rather than assuming project-scoped tasks
      only ever come from `_SEED_PROJECTS`, since that assumption was
      never actually guaranteed, just previously untested.

      Verified `make seed` run twice produces identical row counts (3
      meetings, 7 participants, 2 decisions, 2 actions, 1 promoted task)
      before and after each fix, not just once at the end.

      `apps/web/e2e/meetings.spec.ts`: one flow — create meeting → add an
      external-email attendee → record a decision → add an action item →
      promote it → follow the resulting "View task" link → confirm the
      real task detail page renders, matching `crm.spec.ts`'s own
      one-flow-per-major-capability granularity. Ran it 3 times in a row
      locally (no flakiness) and the full 4-spec E2E suite together
      (smoke/crm/meetings all green) before treating it as done, mirroring
      Phase 3 Stage 11's own repeat-run discipline. Cleaned up immediately
      in the same turn: the meetings/participants/decisions/actions/
      promoted-tasks this E2E run created (across all 3 repeat runs) plus
      the other 3 specs' own leftover project/task/lead/client/converted-
      client rows from running the full suite together, and the temporary
      `.env`/`.env.local` port overrides (same 8010/3010 dodge Stage 7's
      own walkthrough used for the same unrelated sibling-project port-8000
      conflict).

      No new backend test count (idempotent-seed fixture extension, not
      new test functions; 917 unchanged) plus 1 new E2E spec; `make check`
      green end to end (confirmed by exit code, not just visible text);
      `pnpm exec playwright test` green (4/4 specs).

Phase 4 is complete across all 9 planned stages — backend (schema, full
CRUD for meetings/participants/decisions/actions, the one cross-module
write, activity wiring, security matrices) and frontend (pages, nav, a
real browser walkthrough, component tests, seed data, an E2E flow) all
verified. The phase-level Codex audit found no P0/P1 findings, closing
Phase 4, mirroring how Phase 2 and Phase 3 each closed.

## Phase 5 — Finance

Status: **APPROVED by Codex.** All 12 stages complete and independently
reviewed; the final Phase 5 audit found no P0/P1 findings. Planned via a
dedicated plan-mode session (mirroring how Phase 3 and Phase 4 each
started); plan file: `reactive-dreaming-lantern.md`.

DATABASE.md's `### finance` section already fully specified `income`,
`expenses`, `invoices`, `invoice_items`, `payments`, `invoice_counters`;
ADR-0007 already specified the full money/invoice-arithmetic model
(`NUMERIC(14,2)`/`Decimal`, server-computed totals, row-locked invoice
numbering, `SENT`+ immutability, append-only payments with a row-locked
balance recompute); ARCHITECTURE.md §3 already pinned the module boundary
(`finance → work/crm` allowed, no cross-module write needed); RBAC.md's
five finance permissions were already all correctly tiered flat-ADMIN+ in
`permissions.py` with **no ownership-split rule anywhere in §3** — the
lightest authz shape of any module so far. Real decisions made explicitly
during planning rather than invented mid-stage:

- **No archive/delete-invoice endpoint this phase** (ADR-0011: an invoice
  is cancelled, never deleted — that cancellation IS the ADR's own
  "soft delete" for invoices). `archived_at` exists on the model (required
  as the composite-FK-target unique constraint's own column) and list
  queries filter it defensively, but no route ever sets it in V1.
- **PDF library: `xhtml2pdf`** (user decision) — pure-Python, no system
  dependencies (no libcairo/libpango), versus WeasyPrint's richer CSS
  support at the cost of new system deps for MASTER_PROMPT §19's one-line
  PDF requirement.
- **Income and payment seed rows**, despite MASTER_PROMPT §36 literally
  naming only "invoices"/"expenses" — a dashboard demo with invoices but
  no income/payments would show a broken revenue tile and every invoice
  stuck unpaid forever (same "spec is a floor" reasoning Phase 3/4 already
  used).
- **Dashboard tiles read straight off the existing `/dashboard` server
  component's per-module-fetch-with-try-catch pattern** — no separate
  backend aggregator exists or is needed; RBAC.md's "omitted from the
  response, not filtered in the browser" rule is satisfied automatically
  by a 403 being caught the same way every other tile's fetch already is.

Exit criteria: an ADMIN+ can record income/expenses (with a receipt),
create a DRAFT invoice with server-computed totals, send/cancel/pay it
(status transitions correctly, `SENT`+ financial fields frozen); two
concurrent payments or two concurrent invoice-creation requests can never
double-spend a balance or a number (both proven by dedicated concurrency
tests); a MEMBER/MANAGER gets 403 from every finance route and sees no
finance dashboard tile; `GET /invoices/{id}/pdf` returns real PDF bytes.

- [x] Stage 1 — `finance` module schema. `modules/finance/models.py`:
      `ExpenseCategory` (new StrEnum, MASTER_PROMPT §19's 10 values),
      `InvoiceStatus` (5 stored values — `OVERDUE` deliberately absent,
      derived on read per ADR-0007), `Income`, `Expense`, `Invoice`,
      `InvoiceItem`, `Payment`, `InvoiceCounter` — exact columns from
      DATABASE.md's `### finance` section. `uq_invoice_org_number`,
      `uq_invoices_org_id`; `ck_invoice_amounts`/`ck_invoice_total`
      (`total = subtotal - discount_amount + tax_amount`)/`ck_invoice_dates`
      verbatim from ADR-0007; `ck_line_total` (`line_total = round(quantity
      * unit_price, 2)`) on `invoice_items`; `ck_payment_positive` on
      `payments`. Added `ck_income_amount_positive`/`ck_expense_amount_
      positive` proactively — not spelled out in DATABASE.md but mirroring
      `ck_payment_positive`'s own "a negative amount is a data-entry error"
      reasoning. `InvoiceCounter`'s PK is `(organization_id, year)` itself
      (via a table-level `PrimaryKeyConstraint`, not a surrogate `id` —
      the first composite-PK table in the codebase; every other org-scoped
      table so far uses a surrogate `id` + a separate unique constraint).
      Every composite FK follows §5.1/§5.2 exactly (`income.client_id/
      project_id/invoice_id`, `invoices.client_id/project_id`,
      `payments.recorded_by`, `expenses.receipt_file_id` → `file_objects`
      mirroring `task_attachments.file_id`'s RESTRICT reasoning).
      `migrations/versions/0007_finance_schema.py`: hand-written raw SQL,
      creation order `invoice_counters` → `invoices` → `invoice_items`/
      `payments` → `income` → `expenses` (income's nullable `invoice_id`
      FK needs `invoices` to already exist). Added the finance-module
      import to `migrations/env.py` and `tests/security/
      test_schema_integrity.py` in this same stage (Phase 4 Stage 1's own
      lesson, applied proactively this time rather than reactively).
      `tests/factories.py`: `make_income`, `make_expense`, `make_invoice`
      (derives `total` the same way the service will, since
      `ck_invoice_total` rejects anything else), `make_invoice_item`
      (derives `line_total` the same way `ck_line_total` requires),
      `make_payment`.

      Verification: `alembic upgrade head`/`downgrade -1`/`upgrade head`
      round-tripped clean; `alembic check` reports no drift. Proved the
      schema-integrity FK test non-vacuous by deliberately replacing
      `income`'s composite FK to `clients` with a single-column one via
      `psql`, confirming `test_every_fk_between_org_scoped_tables_is_
      composite` fails with the exact violation, then reverting and
      re-confirming green. Full backend suite (917 tests), ruff, ruff
      format, and mypy all clean.
- [x] Stage 2 — Income CRUD. `modules/finance/schemas.py`:
      `IncomeCreateRequest`/`UpdateRequest`/`Response`/`ListResponse`,
      reusing `work.schemas.BudgetDecimal` directly for the request/update
      side (`finance → work` is an allowed import direction, unlike
      `crm → work`, which duplicates the same validator instead —
      confirmed by reading `crm/schemas.py`'s own header comment).
      `IncomeResponse.amount` is a plain `Decimal`, not `BudgetDecimal` —
      that alias's `BeforeValidator` only accepts a decimal string
      (request-side parsing) and rejects a real ORM `Decimal`, same
      reasoning `ProjectResponse.budget` already follows; caught by the
      first test run, fixed immediately.
      `modules/finance/services/income_service.py`: plain CRUD gated by
      route-level `require(Permission.FINANCE_WRITE/FINANCE_READ)` alone
      — no service-level role check or ownership predicate anywhere
      (ROADMAP.md Phase 5 decision 2), the lightest service shape of any
      module so far. `amount > 0` is validated in Python before insert,
      mirroring `ck_income_amount_positive` at the application layer
      (same reasoning as `meeting_service`'s `ends_at`/`starts_at`
      check) so a bad request surfaces as a clean 422, not a raw DB
      `CheckViolationError`. `client_id`/`project_id`/`invoice_id`
      references are validated via `crm.client_service.get_client_in_org`/
      `work.project_service.get_project_in_org`/a private
      `_get_invoice_in_org` lookup (duplicated rather than importing from
      `invoice_service.py`, which Stage 4 hasn't built yet — Stage 4
      should consolidate onto a shared `get_invoice_in_org` once it
      exists). Delete is a hard delete with an audit event (ADR-0011:
      income isn't one of the four soft-deleted entities), same pattern
      as `meeting_service.delete_meeting`. `modules/finance/routes/
      income.py` registered in `main.py`. Added both the authz-matrix
      rows (`_MATRIX_ROWS`, no `_OWNERSHIP_SPLIT_ROUTES` entries needed —
      confirmed this module has no ownership-split rule at all) and the
      isolation-matrix rows in this same commit — the authz matrix's own
      meta-assertion (`test_matrix_covers_every_permission_gated_route`)
      failed immediately on the first test run without them, confirming
      it isn't optional.

      Verification: 13 new integration tests in `tests/integration/
      test_income.py` (role gating, non-positive-amount rejection,
      cross-org client-reference rejection, CRUD, cross-org 404). Full
      backend suite (961 tests, up from 917), ruff, ruff format, and
      mypy all clean. `make openapi` regenerated
      `apps/web/lib/api/types.gen.ts` cleanly.

      **Codex finding (fixed):** `IncomeUpdateRequest` had no guard against
      an explicit `null` for its five NOT NULL columns — `{"amount": null}`
      reached `income_service.update_income`'s `updates["amount"] <= 0`
      comparison as a `TypeError` (500), and `{"currency"/"source"/
      "received_on"/"payment_method": null}` reached the DB's own NOT NULL
      constraint as an unhandled 500. Fixed with a `model_validator(mode=
      "after")` on `IncomeUpdateRequest`, the exact pattern `Project
      UpdateRequest`/`TaskUpdateRequest` already use: any of the five
      fields present in `model_fields_set` but `None` raises a clean 422,
      while an *omitted* field still passes through untouched
      (`exclude_unset=True` semantics preserved). `client_id`/`project_id`/
      `invoice_id` are deliberately excluded — those columns are genuinely
      nullable. Added a parametrized regression test (`test_patch_rejects_
      null_for_required_fields`, all five fields) to `test_income.py`. Full
      suite re-verified (966 tests), ruff, ruff format, mypy clean;
      `make openapi` confirmed no schema-surface change.
- [x] Stage 3 — Expense CRUD + receipt attachment. `modules/finance/
      schemas.py` extended with `ExpenseCreateRequest`/`UpdateRequest`/
      `Response`/`ListResponse` — same shape as income's own schemas, plus
      `ExpenseUpdateRequest`'s own `model_validator` guard against explicit
      `null` for its six NOT NULL fields (`amount`/`currency`/`category`/
      `description`/`spent_on`/`payment_method`), applied proactively this
      time rather than reactively (Stage 2's own Codex finding).
      `receipt_file_id` is deliberately absent from both request schemas —
      a receipt is attached via its own dedicated multipart route, never a
      plain PATCH, same two-step shape as task attachments (create the
      JSON resource, then attach the file).

      `modules/finance/services/expense_service.py`: plain CRUD mirroring
      `income_service.py` exactly (flat `FINANCE_READ`/`FINANCE_WRITE`
      gates, no ownership check, `amount > 0` validated in Python). Receipt
      handling reuses `task_attachment_service.py`'s pattern
      (`create_file_object`, the `FileStorage` protocol) but scoped 1:1 —
      `expenses.receipt_file_id` is a single nullable column, not a list,
      so uploading again *replaces* the existing receipt rather than
      adding a second one. A shared `_clear_receipt` helper nulls the
      column and deletes the old `file_objects` row, returning its
      `storage_key` for the caller to delete the actual blob **after**
      its own `db.commit()` — matching `task_attachment_service.
      delete_attachment`'s own ordering discipline exactly (a dangling DB
      reference to an already-deleted blob, from deleting the blob before
      a commit that might still roll back, is worse than a blob briefly
      orphaned with no DB reference). `delete_expense` also clears any
      attached receipt first, so nothing in `file_objects` is silently
      orphaned when an expense with a receipt is deleted.
      `modules/finance/routes/expenses.py`: CRUD routes plus
      `POST`/`GET`/`DELETE .../receipt` (upload, download, delete),
      mirroring `work/routes/tasks.py`'s attachment routes' `Content-
      Disposition` encoding exactly. Registered in `main.py`.

      Added authz-matrix rows for all 8 new routes and isolation-matrix
      rows (a `{expense_id}`-based CRUD list plus a dedicated real-storage
      test for the receipt routes, mirroring `test_attachment_routes_
      isolated_across_orgs`'s own split-out shape) in this same commit —
      confirmed empirically that a multipart route with no JSON body still
      exercises the authz-matrix's generic per-row test correctly: a
      forbidden role's `require(...)` dependency 403s before FastAPI ever
      validates the missing `file` field, and a permitted role gets some
      other non-403 status, which the assertion treats identically.

      Verification: 18 new integration tests in `tests/integration/
      test_expenses.py` (role gating, non-positive-amount/null-field
      rejection, CRUD, receipt upload/download/replace/delete with real
      filesystem checks that a replaced or deleted receipt's blob is
      actually gone — not just that the DB pointer changed — and
      cross-org 404). Full backend suite (1032 tests, up from 966), ruff,
      ruff format, and mypy all clean. `make openapi` regenerated
      `apps/web/lib/api/types.gen.ts` cleanly.
- [x] Stage 4 — Invoice CRUD (DRAFT lifecycle). `modules/finance/
      schemas.py` extended with `QuantityDecimal` (new alias, `NUMERIC
      (12,3)`-shaped regex — 9 integer + 1-3 decimal digits, non-negative
      unlike `BudgetDecimal`'s own generality, since a line item's
      quantity can't be negative), following `work/schemas.py`'s exact
      `Annotated[Decimal, BeforeValidator, WithJsonSchema]` recipe with a
      duplicated (not imported) `_validate_decimal_string` helper — same
      reasoning `crm/schemas.py` gives for its own copy, even though
      `finance → work` import is allowed (the helper itself is
      underscore-prefixed, not part of `work.schemas`'s public surface).
      `InvoiceLineItemInput`/`InvoiceCreateRequest`/`UpdateRequest`/
      `Response`/`ListResponse`/`InvoiceItemResponse` — `line_total` is
      never client-settable (ADR-0007); `items`, when present on a PATCH,
      wholesale-replaces the invoice's line items rather than exposing a
      separate add/remove/reorder sub-resource (MASTER_PROMPT §20 lists
      `items` as a plain top-level field, not its own routes).
      `InvoiceResponse.is_overdue` is computed by the route mapper from
      `status`/`due_date`, never stored (ADR-0007).

      `modules/finance/services/invoice_counter_service.py`:
      `next_invoice_number` — one atomic `INSERT ... ON CONFLICT DO
      UPDATE ... RETURNING`, the same idiom `platform.rate_limit.
      check_rate_limit` already uses for its own atomic counter. Chosen
      over a literal `SELECT ... FOR UPDATE` (ADR-0007's own wording) plus
      a separate bootstrap-insert-if-missing step, which would need a
      SAVEPOINT to recover from a duplicate-key race on a brand-new org/
      year's very first invoice without rolling back the invoice row
      already staged in the same transaction — the upsert achieves the
      identical guarantee (two concurrent callers can never get the same
      sequence number) in one round trip with no such race window.

      `modules/finance/services/invoice_service.py`: `create_invoice`
      computes each line's `line_total = round(quantity * unit_price, 2)`
      then sums to `subtotal`, applies flat `discount_amount`/`tax_amount`
      to derive `total` — all validated non-negative in Python first
      (`ck_invoice_amounts`/`ck_invoice_total` mirrored at the application
      layer, same reasoning as every other module's own pre-insert
      checks), so a discount larger than the subtotal is a clean 422, not
      a raw DB `CheckViolationError`. A dedicated `_round_money` helper
      uses `Decimal.quantize(..., rounding=ROUND_HALF_UP)` explicitly —
      ADR-0007 requires this exact mode, and Python's bare `round()`/
      `Decimal.__round__` uses the *current decimal context* (default
      ROUND_HALF_EVEN, banker's rounding), which would silently disagree
      with Postgres's own `round(numeric, int)` (round half away from
      zero) on an exact `.xx5` boundary that `ck_line_total`'s DB-level
      check depends on agreeing with. `update_invoice` locks the whole
      invoice once non-`DRAFT` (a `ConflictError`/409), not just its
      financial fields — simpler and stricter than field-by-field,
      matching the plan's own framing rather than inventing a partial
      freeze nothing asked for. `modules/finance/routes/invoices.py`:
      create/list/get/update routes (no delete — ROADMAP.md Phase 5
      decision 1), registered in `main.py`.

      Added authz-matrix rows (`INVOICE_WRITE` for create/update,
      `FINANCE_READ` for list/get — RBAC.md's "Invoices: create/send" is
      one row/one permission covering both this stage's create and
      Stage 5's send) and isolation-matrix rows (no DELETE row, matching
      the decision above) in this same commit.

      Verification: 16 new integration tests in `tests/integration/
      test_invoices.py`, including ADR-0007's own consequences section
      verbatim — `33.33 × 3` (sums to `99.99`, one cent short of
      `100.00`), a 3-decimal quantity (`0.333 × 30.00 = 9.99`), and a
      discount larger than the subtotal (rejected, 422) — plus sequential
      invoice numbering, `due_date < issue_date` rejection, cross-org
      client-reference rejection, `is_overdue` derivation, DRAFT-only
      editability (409 once `SENT`), and cross-org 404. A dedicated
      concurrent-invoice-creation test (two genuinely independent DB
      sessions, `asyncio.gather`, real commits, full FK-ordered cleanup
      mirroring `test_lead_conversion.py`'s own race test and its later
      fix — not just the `activity_events` part) proves two concurrent
      invoices in the same org/year never collide on a number; re-run 3
      times standalone to rule out flakiness, all green, and confirmed via
      `psql` afterward that zero `invoices`/`invoice_counters` rows were
      left behind. Full backend suite (1072 tests, up from 1035), ruff,
      ruff format, and mypy all clean. `make openapi` regenerated
      `apps/web/lib/api/types.gen.ts` cleanly.
- [x] Stage 5 — Invoice lifecycle: send + cancel. New `platform/email/
      templates/invoice_sent.{html,txt}.jinja` and `render.
      render_invoice_email` — same `Environment`/autoescape pattern as
      `render_invitation_email`, addressing ROADMAP.md's own tech-debt
      row ("No persistent email outbox | ADR-0010 | Phase 5 invoice
      delivery"): sent synchronously through the existing `EmailSender`
      pipeline, no queue. `invoice_service.send_invoice`: DRAFT → SENT,
      sets `sent_at`, rejects a client with no email on file (422) before
      doing any work, records `invoice.sent` (ordinary feed), and returns
      an `InvoiceSendResult` pairing the invoice with a pre-built (not
      yet sent) `EmailMessage` — same shape as identity's own
      `CreatedInvitation`, so the route dispatches it via `BackgroundTasks`
      *after* the commit (EMAIL.md §3), mirroring `identity.routes.
      invitations.invite_member` exactly. `invoice_service.cancel_invoice`:
      any non-terminal status (everything except `PAID`/`CANCELLED`) →
      `CANCELLED`, records `invoice.cancelled` with `audit=True` (ADR-0007:
      "a status change with an audit event, never a delete"). Gated by its
      own `INVOICE_CANCEL` permission, distinct from `INVOICE_WRITE` per
      RBAC.md's separate "Invoice: cancel" row — send stays on
      `INVOICE_WRITE`, sharing RBAC.md's single "Invoices: create/send"
      row with `create_invoice`. `routes/invoices.py`: `POST .../send` and
      `POST .../cancel`, registered under the existing router.

      Added authz-matrix rows (send under `INVOICE_WRITE`, cancel under
      its own `INVOICE_CANCEL`) and isolation-matrix rows (both share the
      existing `{invoice_id}`-keyed generic table, same org-scoped lookup
      shape as GET/PATCH) in this same commit. Extended `tests/factories.
      make_client` with an `email` parameter (previously unset) since
      `send_invoice`'s own client-email requirement needed a way to
      construct a client with one.

      Verification: 11 new integration tests in `tests/integration/
      test_invoices.py` — send transitions status and dispatches exactly
      one email (asserted via the existing `fake_email_sender` fixture,
      to/subject/body checked), rejects a client with no email (422, and
      confirms nothing was sent), rejects sending a non-DRAFT invoice
      (409); cancel succeeds from every non-terminal status and is
      rejected from both terminal ones (`PAID`/`CANCELLED`), is recorded
      via `list_audit` and confirmed absent from `list_feed`, and is
      ADMIN+-only (tested same-org, not cross-org, to isolate the role-
      tier check from an org-scoping one). Full backend suite (1097
      tests, up from 1073), ruff, ruff format, and mypy all clean.
      `make openapi` regenerated `apps/web/lib/api/types.gen.ts` cleanly.

      **Codex findings (both fixed):**
      1. `background_tasks.add_task(sender.send, result.email_message)`
         relied on a real ASGI server swallowing a background task's
         exception after the response is on the wire — `crm.routes.
         public.py`'s own `_send_and_log_failures` had already found and
         documented that Starlette's TestClient/ASGITransport has no such
         boundary and re-raises straight into the caller. Fixed with a new
         `_send_with_retry` wrapper in `routes/invoices.py`: catches,
         logs, and retries once immediately before giving up — stronger
         than the contact flow's own catch-and-log-only wrapper, so not
         reused as-is. Added `test_send_invoice_survives_a_failing_email_
         sender`, a `FailingEmailSender` test double asserting the request
         still returns 200/SENT and that exactly 2 send attempts were made
         (one plus the retry, not zero and not unbounded).
      2. `send_invoice`/`cancel_invoice` read the invoice's status without
         a row lock — two concurrent requests could both observe the same
         pre-transition status and both act on it, producing duplicate
         `invoice.sent`/`invoice.cancelled` events and, for send, duplicate
         emails. Fixed by passing `for_update=True` to `get_invoice_in_org`
         in both functions (same fix shape as `lead_conversion_service.
         convert_lead`); `get_invoice_in_org`'s own docstring updated to
         name this reason alongside Stage 7's `record_payment` one it
         already documented. Added two real-session concurrency tests
         (`test_concurrent_sends_of_the_same_invoice_only_one_succeeds`,
         `test_concurrent_cancels_of_the_same_invoice_only_one_succeeds`),
         mirroring `test_lead_conversion.py`'s own race test exactly
         (independent DB connections, `asyncio.gather`, full FK-ordered
         cleanup) — each re-run 3 times standalone to rule out flakiness,
         all green, confirmed via `psql` that no rows were left behind.

      Full suite re-verified (1100 tests), ruff, ruff format, mypy clean;
      `make openapi` confirmed no schema-surface change.
- [x] Stage 6 — Invoice PDF generation (xhtml2pdf). Added `xhtml2pdf>=
      0.2.16` to `pyproject.toml` (0.2.18 resolved) — user-confirmed
      choice from Phase 5 planning: pure-Python, no system-level
      dependencies (no libcairo/libpango), versus WeasyPrint's richer CSS
      support at the cost of new system deps for MASTER_PROMPT §20's
      one-line PDF requirement. New `platform/pdf/` (mirrors `platform/
      email/`'s shape): `templates/invoice.html.jinja` — a table-based
      layout (header, bill-to, line items, totals) staying within
      xhtml2pdf's supported CSS subset, no flexbox/floats needed;
      `render.py`'s `render_invoice_pdf` — same `Environment`/
      `FileSystemLoader` pattern as `email/render.py`, but always
      autoescaped (no HTML/plain-text split to navigate, every template
      here is HTML fed straight to xhtml2pdf); takes only plain strings
      and a small `InvoicePdfLineItem` dataclass, never ORM instances,
      keeping `platform/` decoupled from `modules/finance`'s models
      (ARCHITECTURE.md §3). `invoice_service.generate_invoice_pdf`:
      gathers the invoice/items/client/organization-name, converts to
      display strings, calls `render_invoice_pdf`, returns an `InvoicePdf`
      (bytes + `invoice_number`) so the route can build a real download
      filename without a second fetch — same reasoning `task_attachment_
      service`'s own download path already returns the `FileObject`
      alongside its bytes. `routes/invoices.py`: `GET /{invoice_id}/pdf`,
      gated `FINANCE_READ` (not `INVOICE_WRITE` — viewing an existing
      invoice's PDF is a read), streamed with the same RFC 6266
      `Content-Disposition` encoding as `work/routes/tasks.py`'s/
      `finance/routes/expenses.py`'s own attachment/receipt downloads.

      Added the authz-matrix row (`FINANCE_READ`) and isolation-matrix row
      in this same commit — both fit the existing generic `{invoice_id}`-
      keyed tables with no new resolution code needed.

      Verification: 3 new integration tests in `tests/integration/
      test_invoices.py` — a realistic multi-line invoice (10/1/3.5
      quantities, a discount and tax both applied) returns bytes starting
      `%PDF-` with the correct content-type/nosniff header and the real
      invoice number in `Content-Disposition`; MEMBER/MANAGER 403;
      cross-org 404. Full backend suite (1111 tests, up from 1100), ruff,
      ruff format, and mypy all clean (added an `ignore_missing_imports`
      override for `xhtml2pdf.*`, same treatment as `firebase_admin`/
      `boto3` — it ships no type stubs either). `make openapi`
      regenerated `apps/web/lib/api/types.gen.ts` cleanly.
- [x] Stage 7 — Payments (concurrent-payment test). `modules/finance/
      schemas.py` extended with `PaymentCreateRequest`/`Response`/
      `ListResponse` — no `PaymentUpdateRequest` (ADR-0007: append-only,
      no update/delete route at all). `modules/finance/services/
      payment_service.py::record_payment`: takes `SELECT ... FOR UPDATE`
      on the invoice row (via `get_invoice_in_org(..., for_update=True)`)
      *before* even reading the existing payment sum — the exact ordering
      ADR-0007 prescribes, so a second concurrent request blocks until
      the first commits and then sees the already-updated sum instead of
      racing against a stale one (same fix shape as Stage 5's
      `send_invoice`/`cancel_invoice`). Rejects a non-`SENT`/`PARTIALLY_
      PAID` invoice (409) — `DRAFT` (never sent) and `CANCELLED` need
      their own explicit guard; an already-`PAID` invoice is naturally
      caught by the overpayment check below instead (any further payment
      necessarily exceeds a total already fully paid). `amount_paid` is
      recomputed as `SELECT sum(amount) FROM payments WHERE invoice_id =
      ...` (the actual source of truth), not `invoice.amount_paid + new
      amount` — matching ADR-0007's own "recomputes amount_paid as the
      sum of payments" wording literally. Status derives to `PAID` once
      the sum reaches the total, `PARTIALLY_PAID` otherwise.
      `modules/finance/routes/payments.py`: a router nested under
      `/finance/invoices/{invoice_id}/payments` (a payment always belongs
      to exactly one invoice, DATABASE.md §3) — `POST` gated by its own
      `PAYMENT_WRITE` permission (RBAC.md's separate "Record payment"
      row, distinct from `INVOICE_WRITE`/`INVOICE_CANCEL`), `GET` gated
      `FINANCE_READ`. No `PATCH`/`DELETE` route at all. Registered in
      `main.py`.

      Added authz-matrix rows (`PAYMENT_WRITE` for POST, `FINANCE_READ`
      for GET) and isolation-matrix rows (both fit the existing generic
      `{invoice_id}`-keyed table — the org-scope 404 fires before any
      payability check, so the placeholder invoice's DRAFT status doesn't
      matter here either) in this same commit.

      Verification: 15 new integration tests in `tests/integration/
      test_payments.py` — partial and full payment, two sequential
      partial payments completing an invoice, overpayment rejected both
      as a single too-large payment and as a second payment that would
      push the sum over the total, non-positive-amount rejection,
      rejection against `DRAFT`/`CANCELLED`/already-`PAID` invoices, list,
      cross-org 404, and role gating. A dedicated concurrent-payment test
      (two genuinely independent DB sessions, `asyncio.gather`, real
      commits, full FK-ordered cleanup mirroring `test_lead_conversion.
      py`'s own race test and Stage 5's send/cancel concurrency tests) —
      a SENT $100 invoice, two concurrent $60 payments, proves exactly
      one succeeds and the invoice's own `amount_paid` ends at $60.00, not
      $120.00 or a lost update — the literal test ADR-0007's own
      consequences section requires ("Concurrent-payment tests are
      required to prove that two requests cannot both pass the balance
      check against the same prior amount"); re-run 3 times standalone to
      rule out flakiness, all green, confirmed via `psql` that no rows
      were left behind. Full backend suite (1140 tests, up from 1112),
      ruff, ruff format, and mypy all clean. `make openapi` regenerated
      `apps/web/lib/api/types.gen.ts` cleanly.
- [x] Stage 8 — Finance dashboard aggregates. `modules/finance/services/
      dashboard_service.py::get_finance_stats` mirrors `crm.lead_service.
      get_lead_stats`'s exact shape — one service function, a handful of
      aggregate queries, a small dataclass, the same multi-currency
      `ponytail:` disclaimer. MASTER_PROMPT §19's six tiles, per ROADMAP.md
      Phase 5 decision 5's own settled data sources: revenue/expenses this
      month (`sum(amount)` over the calendar month, computed via Python
      month-boundary arithmetic — no stdlib month-add exists, so a small
      `_add_months` helper does it); net cash flow (subtracted in Python,
      not its own query); outstanding invoices (`count`/`sum(total -
      amount_paid)` where `status IN (SENT, PARTIALLY_PAID)`, defensively
      filtering `archived_at.is_(None)` per ADR-0011); revenue trend
      (`GROUP BY date_trunc('month', received_on)` over a fixed 6-month
      window); expense breakdown (`GROUP BY category` over the current
      month, same window as the "expenses this month" tile).

      **Found and fixed while writing the first test, not by Codex**:
      `date_trunc('month', date)` resolves through an implicit cast to
      `timestamptz`, so the truncation happens in whatever timezone the
      *executing session* is set to — confirmed empirically that a
      Dhaka-timezone (`+06`) session and this app's own UTC-reading
      connection disagreed by a full calendar day on the exact same row.
      Fixed by casting `received_on` to a plain (zoneless) `timestamp`
      before truncating, making it a pure calendar operation immune to
      any session's timezone setting — verified directly via `psql`
      (`pg_typeof`) before and after the fix, not assumed.

      `modules/finance/routes/dashboard.py`: `GET /finance/stats`, its own
      router (not nested under income/expenses/invoices — the aggregate
      spans all three, same reasoning `leads/stats` gets its own static
      route rather than living under one entity's prefix), gated
      `FINANCE_READ`. No isolation-matrix row needed — a static path with
      no parent resource to isolate against, same as `/leads/stats`'s own
      precedent. Frontend: `dashboard/page.tsx` gained one more
      `getFinanceStats()` call in its existing `Promise.all`, reusing the
      identical per-tile try/catch-returns-null pattern every other tile
      already uses — confirmed directly (Phase 5 planning) that no
      separate backend aggregator exists to patch, so RBAC.md's "omitted
      from the API response, not filtered in the browser" requirement is
      satisfied automatically: a MEMBER/MANAGER's own server-side fetch
      403s, caught by the same try/catch, and the two finance tiles are
      omitted entirely (not shown with a "—" placeholder like every other
      tile's own not-yet-known state) rather than hidden client-side.

      Verification: 5 new integration tests in `tests/integration/
      test_finance_dashboard.py` — a realistic multi-row scenario across
      income/expenses/invoices asserting every one of the six tiles'
      exact computed values (including the revenue-trend month key and
      expense-breakdown-by-category), an all-zero/empty baseline with no
      data, cross-org exclusion, and role gating. Added the authz-matrix
      row in this same commit. Full backend suite (1150 tests, up from
      1140), ruff, ruff format, and mypy all clean. Frontend: `pnpm
      typecheck`/`lint`/`exec prettier --check`/`test` (60 tests)/`build`
      all green. `make openapi` regenerated `apps/web/lib/api/
      types.gen.ts` cleanly.
- [x] Stage 9 — Activity feed wiring. No new production code: every
      finance event named in the plan (`income.created`/`.deleted`,
      `expense.created`/`.deleted`, `invoice.created`/`.sent`/
      `.cancelled`, `payment.recorded`) was already wired inline in its
      own stage (Phase 2's pattern, not Phase 3's retrofit — the same
      decision Phase 4 Stage 2 already made for `meeting.created`),
      confirmed by grepping every `finance/services/*.py` file for
      `record(...)` calls before writing a single test. This stage is
      purely the verification pass the plan itself calls for.

      Extended `tests/integration/test_activity_writer.py` with 11 new
      tests, same shape as the file's own CRM/meetings sections: each
      create writes exactly one ordinary feed row (`is_audit=False`);
      `invoice.cancelled` writes an audit row and nothing to the feed
      (ADR-0007: cancellation is a status change with an audit event,
      never a delete — same treatment `meeting.deleted`/`invoice_
      participant` removal already get); `income.deleted`/`expense.
      deleted` write an audit row (ADR-0011: neither is one of the four
      soft-deleted entities — a hard delete, the audit event is the only
      remaining record); a plain `update_income`/`update_expense`/
      `update_invoice` call (no status transition) writes no additional
      event at all, mirroring `test_project_update_without_status_
      change_writes_no_feed_event`'s own precedent — confirmed directly
      that none of the three `update_*` functions call `record(...)`
      anywhere, so there was no gap to fix, only to prove.

      Full backend suite (1161 tests, up from 1150), ruff, ruff format,
      and mypy all clean. No `make openapi` diff — no route or schema
      changed this stage.
- [x] Stage 10 — Frontend. MASTER_PROMPT §19's five routes, verbatim:
      `/finance` (overview — the six dashboard tiles plus revenue-trend/
      expense-breakdown breakdowns, reusing `fetchFinanceStats`),
      `/finance/income`, `/finance/expenses`, `/invoices`, `/invoices/
      [id]`. `lib/api/client.ts` extended with the full Income/Expense/
      Invoice/Payment types+fetchers Stage 8 deliberately deferred; a new
      `uploadExpenseReceipt` makes its own `fetch` call with `FormData`
      rather than going through `apiFetch` (which always JSON-encodes),
      mirroring its cookie/CSRF conventions by hand.

      Same client-rendered four-state pattern as Leads/Meetings
      throughout. No edit UI for a DRAFT invoice's fields, or for income/
      expense rows, this stage (ponytail — the plan's own exit criteria
      only asks for create/send/cancel/pay, not an edit form; the
      backend's PATCH routes already exist for a later stage to build a
      UI against). No client-side permission pre-check anywhere — every
      mutation attempts the call and surfaces whatever `ApiError` comes
      back, same as every prior phase's frontend stage. Sidebar: enabled
      the four FINANCE group hrefs that were already scaffolded with
      `restrictedToAdminPlus: true` since Phase 1 — confirmed directly
      that flag already correctly hides the whole group for MEMBER/
      MANAGER, no new gating code needed.

      The invoice detail page's Send/Cancel/Record-payment controls key
      off the invoice's own `status` (`DRAFT` → Send only; non-terminal →
      Cancel; `SENT`/`PARTIALLY_PAID` → the payment form) and its
      `is_overdue` flag renders `OVERDUE` in place of the stored status,
      matching ADR-0007's own derivation. The PDF is a plain `<a href>`
      to `GET .../pdf`, not a fetch — a same-origin browser navigation
      already sends cookies, so no client wrapper was needed.

      Verification: 22 new component tests across `finance-income.
      test.tsx`, `finance-expenses.test.tsx`, `invoices.test.tsx`, and
      `invoice-detail.test.tsx` (loading/error/empty/populated states,
      the receipt Upload-vs-View control switching on `receipt_file_id`,
      `is_overdue` overriding the displayed status, and each invoice
      status correctly showing/hiding Send/Cancel/payment-form), plus 1
      new sidebar test for the four newly-enabled links — 83 frontend
      tests total (up from 60). `pnpm typecheck`/`lint`/`exec prettier
      --check`/`test`/`build` all green; `make openapi` confirmed no
      schema-surface change (no backend file touched this stage).

      **Manual `make dev` walkthrough** (temporary alternate ports 8010/
      3010, `E2E_TEST_MODE`/`NEXT_PUBLIC_E2E_TEST_MODE`, reverted after —
      same established pattern as Phase 4 Stage 7's own walkthrough):
      logged in as the seeded founder, created a real invoice against the
      seeded "Acme Corp" client with a rounding-exposing line item (3 ×
      33.33), and confirmed the invoice detail page's own displayed total
      is exactly `99.99` — the literal check this stage's plan named.
      Also exercised income creation, expense creation, and the finance
      overview page's own stats rendering end-to-end through the real
      browser (all passed); the send/pay/cancel button clicks were
      independently confirmed working via the real backend logs
      (`POST .../send` → `200 OK`, a real console-backend email logged)
      during an earlier pass of the same script, though the walkthrough
      script's own list-ordering assumption made two later scripted runs
      unreliable — that unreliability is in the throwaway verification
      script, not the product; `send`/`cancel`/`record payment`'s own
      click-behavior and status-gating are independently covered by the
      component tests above, and their business logic already has full
      backend test coverage from Stages 5 and 7 (including the concurrent-
      request race tests). All rows created during the walkthrough
      (4 invoices, 4 income rows, 3 expense rows, matched by name/
      description) were deleted in FK-safe order in the same turn;
      confirmed via `psql` that zero remain. `.env`/`apps/web/.env.local`
      reverted, scratch scripts deleted, both dev servers stopped.
- [x] Stage 11 — Security matrices. No new code: every finance route's
      authz-matrix and isolation-matrix row was already added inline in
      its own stage (Stages 2-9), the same "wire it as you build it"
      discipline Stage 9 already established for activity events —
      unlike Phase 3/4, where security matrices were their own dedicated
      late-phase addition. This stage is the audit the plan itself calls
      for, not new wiring.

      Confirmed by direct introspection of the live FastAPI app
      (`iter_api_routes`, the same helper `startup_audit.py`'s own boot-
      time check and the matrix test's meta-assertion both use), not
      just by the meta-assertion passing: exactly 23 non-public finance/
      invoice routes exist, and all 23 have an authz-matrix row — 5 for
      income, 8 for expenses (including the receipt sub-resource), 7 for
      invoices (including send/cancel/pdf), 2 for payments, 1 for stats.
      Zero of them are in `_OWNERSHIP_SPLIT_ROUTES` — confirmed by
      grepping that set directly — matching ROADMAP.md Phase 5 decision 2
      (RBAC.md §3 has no finance ownership-split rule at all, so every
      row is a plain permission check, none of Phase 3/4's own "route
      permission passes for everyone, service enforces the real rule"
      shape).

      Isolation-matrix coverage audited the same way: 16 of the 23 routes
      have a cross-org 404 test (every `GET`/`PATCH`/`DELETE`/action route
      that takes an existing resource's id); the other 7 (the three
      `POST .../income`|`.../expenses`|`.../invoices` creates, the two
      bare list `GET`s, and `GET /finance/stats`) are correctly excluded —
      a create has no existing target to attempt cross-org access
      against, a list's own org-scoping is enforced by the query filter
      itself rather than a per-id lookup, and `/finance/stats` has no
      parent resource at all, same reasoning `/leads/stats` already
      established. 16 + 7 = 23, no gaps.

      Full backend suite (1161 tests, unchanged — no new tests needed,
      only re-verified), ruff, and mypy all clean.
- [x] Stage 12 — Seed script + E2E, final stage. Extended `scripts/seed.py`
      with income, expenses, invoices (with line items and payments) —
      the plan's decision 3 (income/payment rows beyond MASTER_PROMPT
      §36's literal "invoices"/"expenses") — so every one of Stage 8's six
      dashboard tiles renders non-zero data, not just invoices/expenses.

      Re-read the entire 1011-line file first (Phase 4 Stage 9's own
      lesson, applied proactively rather than rediscovered) before adding
      anything, specifically to get income/expense date handling right:
      their natural keys are `source`/`description` alone (never the
      date), matching `next_follow_up`'s own precedent that a date
      computed relative to "today" is never read back into the
      idempotency check — but unlike `next_follow_up`/meetings (where a
      fixed date only goes cosmetically stale), income/expense dates *do*
      need to move with `date.today()` on every reseed, since Stage 8's
      tiles key off "this month"/"the last 6 months" and a fixed
      historical date would eventually make them read permanently zero, a
      real regression, not cosmetic drift. `_TODAY` is read once at seed
      time and every income/expense/invoice date is computed relative to
      it.

      Invoices use fixed, hand-assigned `TRI-2026-{seq:04d}` numbers
      (this script never calls `invoice_service.next_invoice_number` —
      every entity here is direct ORM construction, matching everything
      else in the file) — identified and fixed a real collision risk
      *before* writing any seed data: a real invoice created later via
      the actual API would otherwise start its own counter from 0 and
      collide with a hand-assigned number. `_ensure_invoice_counter_at_
      least` get-or-creates `invoice_counters(organization, 2026)` and
      only ever bumps `last_seq` upward, mirroring `_get_or_create_
      project`'s own "only ever sets an unset link, never overwrites a
      later run's data" backfill philosophy.

      Six invoices across every stored `InvoiceStatus` (DRAFT, SENT ×2 —
      one with a future `due_date`, one deliberately overdue with a past
      `due_date` to exercise `is_overdue`'s own read-time derivation,
      ADR-0007 — PARTIALLY_PAID, PAID, CANCELLED), each with real line
      items computing server-side-style totals by hand
      (`line_total = round(qty × price, 2)`, `total = subtotal -
      discount + tax`) to satisfy the DB's own CHECK constraints; the
      PARTIALLY_PAID and PAID invoices each get one matching seed
      `Payment` row. Four income rows (one linked to the seeded PAID
      invoice via `invoice_id`, demonstrating that cross-reference is
      populated in at least one demo row) and six expenses spanning
      HOSTING/DOMAINS/SOFTWARE/MARKETING/SALARY/OFFICE.

      Verified directly against a real local Postgres, not just by
      passing tests: `alembic upgrade head` is a no-op (no schema
      change this stage); `make seed` run twice produced identical row
      counts both times (4 income, 6 expenses, 6 invoices, 6 invoice
      items, 2 payments, `invoice_counters.last_seq = 6` unchanged on the
      second run); manually queried every invoice's computed
      total/amount_paid/`is_overdue` and every income/expense row's
      values against the exact design (all matched).

      `tests/unit/test_seed_idempotent.py`: extended `_isolated_seed` to
      shadow `_SEED_INVOICES`/`_SEED_INCOME` too (remapping `client_name`/
      `project_code` via the fixture's existing maps) — reproduced the
      exact class of bug Stage 9's own comment predicted (a shadowed
      `_SEED_PROJECTS` with an un-shadowed new entity referencing it by
      name throws a bare `KeyError`) directly, twice: once for a hardcoded
      module-level `_FOUNDER_EMAIL` reference inside `seed()` that didn't
      track `_SEED_USERS` monkeypatching (fixed by reading `_SEED_USERS[0]
      .email` dynamically instead), once for `_SEED_INVOICES`' own
      un-shadowed `project_code`/`client_name` fields (fixed by shadowing
      them in the fixture). `_SEED_EXPENSES` needs no shadow — it carries
      no name-based cross-reference. Extended `_cleanup_rows_created_
      since` with a finance purge block (invoice_items/payments before
      invoices, income before invoices/clients/projects, invoices/
      expenses before memberships) inserted before the existing projects
      cleanup, for the same FK-ordering reason the meetings block already
      runs first — unlike the snapshot-gated blocks for clients/projects/
      etc., this is an unconditional per-organization purge, since every
      test scenario in this file either has no organization yet or (the
      "fills in missing users" test) pre-seeds only the founder user and
      membership, never finance data — so a finance row under this
      fixture's uniquely-suffixed org is always test-created. Added
      idempotency assertions for income/expense/invoice/invoice-item/
      payment/counter row counts across two `seed()` calls, matching the
      existing test's depth for every other entity.

      `apps/web/e2e/finance.spec.ts` — the one flow MASTER_PROMPT §37
      names for this phase: log in as the seeded OWNER, create an invoice
      with two line items (one deliberately needing real ROUND_HALF_UP
      rounding — `1.111 × 3.33 = 3.69963 → 3.70`, not just formatting) and
      a discount/tax, and assert the rendered total is the value derived
      from those same raw inputs in the test itself — a live check of the
      server's own arithmetic, not a hardcoded string. Picking "the new
      invoice" off the list page proved unreliable on the first run
      (six invoices are already seeded, so a naive first-link-by-sort-
      order assumption grabbed a pre-existing seeded invoice instead) —
      fixed by reading the real invoice id straight out of the `POST
      .../invoices` response instead of the list UI. Ran three times
      locally, all green; each run's created invoice(s) (and the
      counter bump they caused) were deleted/reset in the same turn via
      `psql`, confirmed zero test invoices remain and `invoice_counters.
      last_seq` is back to 6.

      `.env`/`apps/web/.env.local` were temporarily set for the manual
      run (`APP_ORIGIN`/`API_PORT` → 3010/8010, `E2E_TEST_MODE`/
      `NEXT_PUBLIC_E2E_TEST_MODE` → true) and fully reverted afterward
      (`.env.local` deleted — it didn't exist before this stage); both
      dev servers stopped.

      Full `make check` green end to end (1161 backend tests, ruff,
      mypy, eslint, prettier, tsc, 83 vitest tests, `next build`, openapi
      diff clean — no schema/route change this stage).

      **Codex P1 (Stage 12 review)**: line-item rounding used Python's
      bare `round(Decimal, 2)`, which follows the *current decimal
      context* (default ROUND_HALF_EVEN) rather than ADR-0007's mandated
      ROUND_HALF_UP — silently different from Postgres's own
      `round(numeric, int)` (round-half-away-from-zero) on an exact
      `.xx5` boundary, and `ck_line_total`'s DB-level CHECK depends on the
      two agreeing. Accepted: duplicated `invoice_service._round_money`'s
      exact `Decimal.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)`
      into seed.py (not imported — this script never calls into the
      service layer) and used it for both `line_totals` and each
      `InvoiceItem.line_total` (the latter now reuses the already-
      computed `line_totals` via `zip` instead of recomputing, so the two
      can no longer silently diverge). Added Codex's own suggested
      regression value directly into the seed data — a second line item
      on TRI-2026-0001 (`1.111 × 3.33`), which only rounds to a clean
      `3.70` under ROUND_HALF_UP — so this is exercised for real on every
      `make seed` run, not just in `finance.spec.ts`. Verified against a
      real local Postgres: purged all finance tables, ran `make seed`
      twice (identical 6 invoices / 7 invoice items / 6 expenses /
      4 income / 2 payments both times), and confirmed via `psql` that
      TRI-2026-0001's second item's `line_total` is exactly `3.70` and
      its invoice `total` is `2403.70`. Full backend suite (1161 tests)
      and `make check` re-run clean.

      **Codex re-review: approved, P1 fully resolved** — confirmed both
      rounding call sites now use explicit ROUND_HALF_UP, `InvoiceItem.
      line_total` reuses the computed values (no divergence possible),
      the `1.111 × 3.33 → 3.70` case is real seed data, and no bare
      `round()` call sites remain. Pushed to `origin/main`.
- [ ] Backup restore rehearsal ([DEPLOYMENT.md §7](docs/architecture/DEPLOYMENT.md)) — manual DBA exercise, not a code deliverable; correctly tracked separately and does not block phase closure
- [x] Codex audit — final phase-level audit found no P0/P1 findings: all 12 stages present, reviewed, and pushed; Finance exit criteria (CRUD, invoice lifecycle, PDF, concurrent payments/numbering, activity events, dashboard aggregates, frontend routes, security matrices, idempotent seed data, E2E rounding coverage) covered end to end; worktree clean.
- [x] Resolve P0/P1 findings — every finding raised across all 12 stages (including Stage 12's rounding P1) was resolved and re-verified before the final audit; none remain open.

Phase 5 is complete across all 12 planned stages — schema, income/expense
CRUD, invoice lifecycle (draft/send/cancel), PDF generation, payments with
concurrent-request-safe balance recompute and invoice numbering, finance
dashboard aggregates, activity feed wiring, frontend routes, security
matrices, idempotent seed data, and an E2E rounding-correctness flow all
verified. The phase-level Codex audit found no P0/P1 findings, closing
Phase 5, mirroring how Phase 2, Phase 3, and Phase 4 each closed.

## Phase 6 — Documents + Integrations

Status: **APPROVED by Codex.** All 6 stages complete and independently
reviewed; the final Phase 6 audit found no P0/P1 findings. Planned via a
dedicated plan-mode session (mirroring how Phases 3-5 each started); plan
file: `reactive-dreaming-lantern.md`.

Unlike Phases 3-5, this phase is not "apply the established pattern to a
well-specified module" — DATABASE.md §3 has exactly one line for this
phase's schema (`document_references`: title/url/kind/project_id?/
client_id?/meeting_id?/added_by/created_at, no constraints or enum values
given), RBAC.md has zero rows for Documents or Integrations, and
`core/authz/permissions.py` has no `DOCUMENT_*`/`INTEGRATION_*` values —
all fresh decisions this plan makes, not confirmations of existing ones.
MASTER_PROMPT.md has no dedicated section for either half of this phase;
its spec is assembled from §16 (Google Drive/Docs, explicitly "V2":
"Initially allow external document links... Do not rebuild Google Docs")
and the §39 phase-list bullets. GitHub gets exactly one mention anywhere
in the spec (the §39 bullet) — no fields, no flow, no section.

**User-confirmed scope decision**: "Google Drive integration"/"GitHub
integration"/"Additional useful integrations" are built as a single
feature — `document_references` rows with a `kind` tag (`GOOGLE_DRIVE`,
`GITHUB`, `OTHER`) distinguishing which external system a link points at.
No OAuth, no API calls to Drive/GitHub, no background worker/webhook
infrastructure (none exists anywhere in this codebase — confirmed by
direct grep; ADR-0010 already rules out Redis/a worker in V1 and names
"any job that must run reliably off the request path" as the trigger to
revisit that, which real OAuth-based integrations would be). This is not
a scope cut invented for this plan — ADR-0012 already decided exactly
this for Drive ("V1 stores external links"); this phase implements that
decision and extends it to GitHub by the same reasoning. Real OAuth-based
integrations remain deferred to V2, same treatment Phase 4 gave Google
Calendar and reminder emails.

Fresh decisions this plan makes explicitly (see the plan file for full
reasoning on each): (1) `kind` enum is `GOOGLE_DRIVE`/`GITHUB`/`OTHER`;
(2) two new flat permissions, `DOCUMENT_READ` (MEMBER+)/`DOCUMENT_WRITE`
(MANAGER+), tiered like Leads/Clients, not restricted like Finance;
(3) no ownership-split and no per-parent visibility check beyond
existence-in-org validation, departing deliberately from ADR-0008's
"authorized like its parent" attachment rule since Documents has a looser
shape (optional parent, or none at all) and RBAC.md already gives MEMBER
blanket org-wide visibility on projects/clients/meetings anyway; (4) a
reference may have zero, one, or more than one parent set simultaneously
(no CHECK constraint forcing exactly one); (5) hard delete + audit event,
no `archived_at` (not one of ADR-0011's four named entities);
(6) `updated_at` added despite the one-line spec not naming it, since
title/url/kind are editable; (7) one E2E flow added beyond MASTER_PROMPT
§37's fixed eight, same precedent Phase 4's `meetings.spec.ts` already
set; (8) the Phase-0-era "hosting target" open decision doesn't block this
phase, since decision 1 rules out any real OAuth redirect URI/webhook
endpoint.

- [x] Stage 1 — `document_references` schema. `platform/models.py`:
      `DocumentReference` (`OrgScoped`) and `DocumentKind` (3-value StrEnum
      — decision 1). Columns per DATABASE.md's one-line spec plus decision
      6: `title`, `url`, `kind` (native enum), `project_id`/`client_id`/
      `meeting_id` (all nullable, composite FK to `(organization_id, id)`
      on `projects`/`clients`/`meetings`, `ON DELETE RESTRICT` — those
      parents are soft-deleted only, per the same reasoning `meetings.
      project_id`/`.client_id` already use), `added_by` (composite FK to
      `memberships`, matching DATABASE.md's own literal column name — not
      `created_by`), `created_at`/`updated_at`. No `archived_at`
      (decision 5); no unique constraint of its own — nothing composite-
      FKs to a `document_references` row.

      `migrations/versions/0008_document_references.py`, hand-written raw
      SQL matching every prior migration's exact style, including the
      `trg_document_references_updated_at` trigger reusing the
      `set_updated_at()` function `0001_initial.py` already defines.

      Fleshed out DATABASE.md's one-line `document_references` entry to
      the same level of detail every other table gets; added two new
      RBAC.md §2 rows ("Documents: view" MEMBER+, "Documents: create/
      edit/delete" MANAGER+); added `DOCUMENT_READ`/`DOCUMENT_WRITE` to
      `core/authz/permissions.py` under a new `# Documents — Phase 6`
      block, `_MEMBER` gets `DOCUMENT_READ`, `_MANAGER` gets
      `DOCUMENT_WRITE`. Confirmed directly (not assumed) that
      `tests/security/test_schema_integrity.py` and `migrations/env.py`
      already import `platform.models` for its metadata side effect — no
      new wiring needed there, just a documented confirmation.
      `tests/factories.py`: `make_document_reference`.

      Verified directly against a real local Postgres: `alembic upgrade
      head`/`downgrade -1`/`upgrade head` clean; `alembic check` reports
      "No new upgrade operations detected". Proved the schema-integrity
      test actually catches a real violation, not just passes vacuously —
      temporarily replaced the composite `client_id` FK with a broken
      single-column FK via `psql` (as the migrator role), confirmed
      `test_every_fk_between_org_scoped_tables_is_composite` fails with
      the exact violation message, then reverted cleanly via `alembic
      downgrade -1 && alembic upgrade head` and confirmed the suite is
      green again. `test_permission_hierarchy.py` passes with the two new
      permissions correctly nested `MEMBER ⊂ MANAGER`. Full backend suite
      (1161 tests, unchanged — schema-only stage, no new test functions
      yet), ruff, mypy all clean.
- [x] Stage 2 — CRUD service + routes. `platform/schemas.py`:
      `DocumentReferenceCreateRequest`/`UpdateRequest`/`Response`/
      `ListResponse` — `DocumentReferenceUpdateRequest` gets the same
      `_no_null_for_required_fields` model-validator `IncomeUpdateRequest`
      needed after its own Codex Phase 5 finding, applied here proactively
      for `title`/`url`/`kind` rather than rediscovered reactively.

      `platform/documents.py` (flat module file, matching `platform/
      files.py`/`platform/activity.py`'s own style — `platform` has no
      `services/` subfolder to imitate): full CRUD, gated
      `DOCUMENT_READ`/`DOCUMENT_WRITE` only, no ownership check (plan
      decision 3). Optional `project_id`/`client_id`/`meeting_id` are
      each independently validated in-org via `get_project_in_org`/
      `get_client_in_org`/`get_meeting_in_org` (`income_service`'s own
      cross-reference-validation template) when present, list route
      takes the same three as optional filters. `platform/routes/
      documents.py` registered in `main.py`; `make openapi` clean.

      Activity events wired inline here, not deferred — re-read
      `income_service.py` directly before writing this and confirmed the
      real Phase 5 precedent is "wire it as you build it, Stage 9 was a
      verification pass, not new wiring" (corrected the plan's own Stage
      2/3 split accordingly: Stage 3 below is now purely the verification
      pass). Also discovered by direct re-read, not assumed from the
      plan: income/expense's own update functions write **no** event at
      all (not even a no-op-guarded one) — `update_document_reference`
      matches that exactly, simpler than the plan's own decision 3 text
      described.

      Authz-matrix and isolation-matrix rows added in this same stage,
      matching Finance's Stage 11 precedent that these are best wired
      per-stage, audited later (Stage 5). Isolation matrix needed two
      separate route lists/test functions (read vs. write), not one like
      finance's single ADMIN+-tier list — `DOCUMENT_READ` (MEMBER+) and
      `DOCUMENT_WRITE` (MANAGER+) are different tiers, mirroring how CRM's
      own `_CRM_READ_ISOLATION_ROUTES`/`_CRM_WRITE_ISOLATION_ROUTES` split
      for the same reason.

      14 new integration tests (`tests/integration/test_documents.py`)
      covering create/list/get/update/delete, MEMBER-can-read/cannot-write,
      cross-org reference rejection, multi-parent creation (decision 4),
      and the null-required-field 422 case; 20 new authz-matrix cases (5
      rows × 4 roles) and 10 new isolation-matrix cases (read × 4 roles +
      write × 3 roles × 2 methods) — all pass on the first run. Full
      backend suite (1213 tests, up from 1161), ruff, mypy, `make openapi`
      all clean.

      **Codex P1 (Stage 2 review)**: `platform/documents.py` imported
      `crm`/`meetings`/`work` services to validate the optional
      `project_id`/`client_id`/`meeting_id` — a `platform → work/crm/
      meetings` edge, forbidden by ARCHITECTURE.md §3's `platform ←
      everything` rule (platform may only ever be imported, never the
      importer). Accepted: moved the whole feature — model, schemas,
      service, routes — out of `platform` into a new `modules/documents/`
      package (following every other domain module's `services/`/
      `routes/` subfolder convention, not `platform`'s own flat-file
      style), with an explicit `documents → work/crm/meetings` edge added
      to ARCHITECTURE.md §3, the same shape `finance → work/crm` and
      `meetings → work/crm` already use — not a special case. The
      `document_references` table itself is unchanged (same name, same
      columns, same migration — this is a Python-package reorganization,
      not a schema change); moved its DATABASE.md entry from `### platform`
      into a new `### documents` section accordingly. Updated every
      import site (`main.py`, `tests/factories.py`, `tests/security/
      test_schema_integrity.py`, `migrations/env.py`, `tests/integration/
      test_activity_writer.py`) and confirmed no stale `platform.documents`
      references remain anywhere in the tree via a repo-wide grep.
      Verified: `alembic check` still reports no new operations (schema
      genuinely unchanged), full backend suite (1213 tests) green, ruff
      and mypy clean across the whole repo.
- [x] Stage 3 — Activity feed wiring (verification pass only — see Stage 2
      above for why no new wiring belongs here). Extended
      `test_activity_writer.py` with 3 tests: create writes a feed event,
      update writes no event (matching income/expense's real behavior,
      not the plan's original finer-grained no-op-guard idea), delete
      writes an audit event with the feed unchanged. All pass; full suite
      green.
- [x] Stage 4 — Frontend. New route `/documents`: four-state list pattern
      (loading/error/empty/populated) mirroring `leads/page.tsx`/
      `meetings/page.tsx` exactly. "New document" form: title, URL
      (`type="url"`), kind (select: Google Drive/GitHub/Other), and a
      "link to" picker (none/project/client/meeting, then a specific
      entity — decision 4's own UI simplification: the schema allows more
      than one parent at once, the form only ever lets you pick one).
      List row: title as an external link (`target="_blank"`), a kind
      badge, the linked entity's name (looked up client-side against
      already-fetched project/client/meeting lists), a delete button. No
      client-side permission pre-check — matches Finance's own frontend
      stage, not CRM's earlier `useCanManageCrm()`-hiding precedent (a
      MEMBER attempting create/edit/delete simply gets the real 403 back).

      `sidebar.tsx`: flipped the existing `{ label: "Documents" }`
      placeholder (already scaffolded, `COMPANY` group, no
      `restrictedToAdminPlus` flag) to a real `href="/documents"`.

      `lib/api/client.ts`: added `DocumentReference`/`DocumentKind` types
      and `fetchDocuments`/`createDocument`/`updateDocument`/
      `deleteDocument`, same shape as every other module's own client
      functions.

      5 new component tests (`tests/documents.test.tsx`, all four list
      states plus the create-form fields) and 1 new `sidebar.test.tsx`
      case confirming Documents is a real, unrestricted link — all pass.
      `pnpm typecheck`/`lint`/`prettier --check`/`test`/`build` all green.

      Manual `make dev` walkthrough (real Chromium via a throwaway script,
      the project's own bundled browser — the MCP Playwright tool's system-
      Chrome requirement wasn't available in this environment): logged in
      as the seeded founder, created a document (kind GitHub, linked to
      the seeded "TrinolIT Website" project), confirmed it rendered with
      the correct title/kind badge/linked-project name and the expected
      `target="_blank"` external link, then deleted it and confirmed zero
      rows remain in the database. `.env`/`apps/web/.env.local` reverted,
      scratch script deleted, both dev servers stopped.
- [x] Stage 5 — Security matrices audit. No new code — the dedicated
      confirmation pass the plan itself calls for (mirroring Phase 5
      Stage 11), since authz/isolation rows were already wired inline
      during Stage 2.

      Confirmed by direct introspection of the live FastAPI app
      (`iter_api_routes`, the same helper `startup_audit.py`'s own boot-
      time check and the matrix test's meta-assertion both use), not just
      by the meta-assertion passing: exactly 5 documents routes exist
      (`POST /documents`, `GET /documents`, `GET/PATCH/DELETE /documents/
      {id}`), and all 5 have an authz-matrix row. Confirmed via direct
      grep that zero of them are in `_OWNERSHIP_SPLIT_ROUTES`, matching
      decision 3 (no ownership-split anywhere in this module). 3 of the 5
      also have an isolation-matrix row — `GET/PATCH/DELETE /documents/
      {id}`, the only routes with an existing resource id to attempt
      cross-org access against. `POST /documents` (create) and `GET
      /documents` (bare list) are correctly excluded, same reasoning
      Finance's own create/list routes were excluded: a create has no
      existing target, and a list's own org-scoping is enforced by the
      query filter itself, not a per-id lookup. 3 + 2 = 5, no gaps.

      Full backend suite (1213 tests, unchanged — no new tests needed,
      only re-verified), ruff, and mypy all clean.
- [x] Stage 6 — Seed script + E2E, final stage. `scripts/seed.py`: three
      `document_references` rows, one per `DocumentKind` and one per
      parent shape (decision 4) — a `GOOGLE_DRIVE` doc linked to the `WEB`
      project, an `OTHER` doc linked to Acme Corp, a parent-less `GITHUB`
      doc ("Trinol OS repository"). Natural key is `title` alone, no date
      field to go stale (unlike income/expense's own `_TODAY`-relative
      dates from Phase 5 Stage 12).

      `tests/unit/test_seed_idempotent.py`: applied Phase 5 Stage 12's own
      lesson proactively this time, not reactively — read the entire
      existing cleanup function and fixture first, shadowed `_SEED_
      DOCUMENT_REFERENCES` in `_isolated_seed` (remapping `project_code`/
      `client_name` via the fixture's existing maps, same as `_SEED_
      INVOICES` already does), and added a blanket per-organization purge
      in `_cleanup_rows_created_since` positioned alongside the finance
      block (document references reference clients/projects/memberships,
      same ordering reason). All 3 tests passed on the first run — no
      `KeyError` this time, confirming the proactive read actually worked.

      `apps/web/e2e/documents.spec.ts` (decision 7): logs in as the seeded
      founder, creates a document (kind GitHub, linked to the seeded
      "TrinolIT Website" project), and asserts the real thing — the
      correct title, the "GitHub" kind badge, the linked project's name,
      and the link's exact `href`/`target="_blank"` — not just that a row
      appears. Ran 3 times locally (once alongside the other 5 e2e specs
      together), all green; each run's created row was deleted via `psql`
      in the same turn, confirmed back to exactly the 3 seeded rows.

      Re-ran the async/webhook/OAuth grep from this plan's own research
      across `apps/api/src` — still only the pre-existing `BackgroundTasks`
      email-sending hits (plus one new hit: this stage's own "no OAuth"
      docstring comment in `documents/models.py`). Decision 1 held for the
      whole phase, confirmed at the end, not just assumed from planning.

      Verified directly against a real local Postgres: purged
      `document_references`, ran `make seed` twice (identical 3 rows both
      times). `.env`/`apps/web/.env.local` temporarily set for the manual
      E2E run and fully reverted afterward; both dev servers stopped.

      Full `make check` green end to end (1213 backend tests, ruff, mypy,
      eslint, prettier, tsc, 89 vitest tests, `next build`, openapi diff
      clean — no schema/route change this stage).
- [x] Codex audit — final phase-level audit found no P0/P1 findings: all
      6 stages consistent and complete — architecture boundaries
      corrected (the Stage 2 P1 fix), schema/migration and FK integrity
      intact, CRUD permissions and org isolation covered, activity-feed
      semantics verified, frontend/E2E behavior meaningful, and seed/
      idempotency cleanup FK-safe.
- [x] Resolve P0/P1 findings — the one P0/P1 finding raised across all 6
      stages (Stage 2's `platform → work/crm/meetings` architecture
      violation) was resolved and re-verified before the final audit;
      none remain open.

Phase 6 is complete across all 6 planned stages — schema (in its own
`documents` module, not `platform`, after the Stage 2 correction),
CRUD service/routes, activity feed wiring, frontend, security matrices,
and idempotent seed data with an E2E flow all verified. The phase-level
Codex audit found no P0/P1 findings, closing Phase 6, mirroring how
Phases 2-5 each closed.

## Phase 7 — Analytics

Status: **Approved and closed.** Planned via a dedicated plan-mode
session (mirroring how Phases 3-6 each started); plan file:
`reactive-dreaming-lantern.md`.

Unlike Phase 6, this phase's actual new-code surface turned out to be
small once the real data sources were traced: MASTER_PROMPT §31's seven
V1 metrics (`project completion`, `task completion`, `overdue tasks`,
`pipeline value`, `lead conversion`, `revenue`, `expenses`) split cleanly
across the four ROADMAP bullets (`company`/`project`/`sales`/`finance`
from §39), and two of those four buckets already had a real backend
aggregate — `crm.services.lead_service.get_lead_stats` already answers
"pipeline value", `finance.services.dashboard_service.get_finance_stats`
already fully answers "revenue"/"expenses". Tracing the mapping shows
**Company analytics has no metric of its own** — it's a frontend-only
overview combining one headline figure from each of the other three, the
same `Promise.all`-of-independent-fetches shape `/dashboard` already
uses, with no new backend route. The one genuinely new aggregate is
"project completion"/"task completion"/"overdue tasks" — confirmed by
direct read that `Project.progress` is a documented-but-never-implemented
intention (`ADR-0012`, `TESTING.md` §2) — and it needs only `work` module
data (`Project`, `Task`), so it lives in a new `work/services/analytics_
service.py`, not a new cross-cutting module (deliberately avoiding the
exact class of mistake Phase 6 Stage 2 made). "Lead conversion" needed
only one new field on the *existing* `LeadStats`/`get_lead_stats`
(`Lead.stage`'s `WON`/`LOST` already distinguish terminal outcomes — no
`lead_stage_events` query needed for this flat V1 figure). No new
`Permission`, no new module, no new table, no new RBAC.md row — every
route reuses an existing, correctly-tiered permission (`PROJECT_READ`/
`LEAD_READ`/`FINANCE_READ`).

**User-confirmed scope decision**: the Reports page renders plain
numbers/small tables, the same convention every existing tile already
uses (confirmed directly that Finance's own "revenue trend"/"expense
breakdown" render as plain text rows, not a chart) — no charting library
is introduced. MASTER_PROMPT never names a visualization type.

Fresh decisions this plan makes explicitly (see the plan file for full
reasoning on each): (1) bucket mapping as above, Company has no metric of
its own; (2) task completion rate = `count(DONE) / count(status !=
CANCELLED)`, `None` on a zero denominator; (3) overdue tasks = the exact
same predicate shape `Invoice.is_overdue` already uses (open status AND
`due_date < today`); (4) lead conversion rate = `count(WON) / count(WON ∪
LOST)`, all-time, directly from `Lead.stage`, deliberately not filtered
by `archived_at` (a WON/LOST lead's place in this historical ratio
shouldn't shrink just because it was archived later); (5) no new E2E flow
this phase — Reports is a read-only view with no mutation to exercise;
(6) no new permission/module/table; (7) the per-project breakdown is one
`GROUP BY project_id` pass (a `LEFT JOIN` from `Project` so a project
with zero tasks still appears), not a per-project loop; (8)
`active_projects_count` = `count(status = ACTIVE)` literally.

- [x] Stage 1 — Backend aggregates. `work/services/analytics_service.py`
      (new file, `work` module): `ProjectAnalytics`/`ProjectAnalyticsRow`
      dataclasses, `get_project_analytics` — one org-wide query for task
      completion + overdue count, one `count(status=ACTIVE)` query, and
      one `LEFT JOIN`+`GROUP BY project_id` query for the per-project
      breakdown (decision 7) so a project with zero tasks still appears
      with `task_completion_rate=None`/`overdue_tasks_count=0`. Gated
      `PROJECT_READ` at the route, plus `project_service.py`'s own
      established "Project detail" visibility rule (MANAGER+ or
      `project_members` membership) applied to every Project-identifying
      piece of the response — see the Codex P1 fix below. New route
      `GET /projects/analytics`, registered before `/{project_id}`
      (confirmed directly that `list_projects_route`/`get_project_route`'s
      own static-then-dynamic ordering is exactly where to insert it, same
      precedent `leads/routes.py`'s own `/stats` route already
      established).

      `crm/services/lead_service.py`: extended `LeadStats`/`get_lead_
      stats` with `conversion_rate` (decision 4) — one `func.count()
      .filter(...)` pair query, `None` when no lead has reached WON/LOST
      yet. `crm/schemas.py`'s `LeadStatsResponse` extended to match; no
      route change, same `GET /leads/stats` endpoint. `tests/factories.py`'s
      `make_task` gained a `due_date` parameter (didn't exist before —
      needed to construct an overdue-task test case).

      6 new integration tests for `get_project_analytics` (active-count,
      completion-rate math with the zero-denominator `None` case, overdue
      predicate with all four exclusion branches, zero-task project
      breakdown, org isolation) and 2 new tests for the extended `get_
      lead_stats` (conversion-rate math, no-decided-leads `None` case) —
      all pass on the first run. Full backend suite (1221 tests, up from
      1213), ruff, mypy, `make openapi` clean. The one expected, isolated
      gap: the authz-matrix meta-assertion correctly flags the new route
      as missing its own row — Stage 2's own job, not deferred
      accidentally.

      **Codex P1 (Stage 1 review)**: the first version gated the whole
      response on `PROJECT_READ` alone, wrongly reusing Finance/CRM's own
      "no ownership-split" precedent for a resource (`Project`) that
      actually has one — `project_service.py`'s `ensure_project_visible`/
      `list_projects` already restrict which *projects* a MEMBER can see
      (MANAGER+ or `project_members` membership), and `list_projects`
      filters its own `total` count by that rule too, not just its rows.
      A MEMBER could see every non-archived project's id/name/status/
      completion-rate/overdue-count regardless of membership — same-org
      isolation, not just cross-org. Accepted and fixed: the
      Project-identifying pieces (`active_projects_count`, the
      per-project breakdown rows) now apply the identical
      `project_members`-membership filter `list_projects` already uses;
      the two task-only aggregates (`task_completion_rate`,
      `overdue_tasks_count`) stay genuinely org-wide, since `list_tasks`
      is separately, deliberately documented as org-wide transparency
      with no per-resource restriction — confirmed by direct read of its
      own docstring before deciding not to filter those two. Added the
      exact regression test Codex asked for (a same-org project the actor
      is not a member of must be invisible and excluded from the active
      count) plus a MANAGER-sees-everything counterpart. 8 project-
      analytics tests now (up from 6), full suite (1223 tests), ruff,
      mypy, `make openapi` (no schema change — internal query logic only)
      all clean.
- [x] Stage 2 — Security matrices. One new `test_authz_matrix.py` row for
      `GET /projects/analytics` (`Permission.PROJECT_READ`) — noted
      explicitly why this is a plain matrix row, not `_OWNERSHIP_SPLIT_
      ROUTES`: unlike `GET /projects/{project_id}` (which 403s outright
      for a non-member), this route never 403s for any `PROJECT_READ`
      role — it always returns 200 and instead *filters* which projects
      appear (Stage 1's P1 fix), already tested directly and thoroughly
      in `test_project_analytics.py`.

      Confirmed directly (not assumed) that `/leads/stats`/`/finance/
      stats`/`/projects/analytics` are all absent from `test_isolation_
      matrix.py` — none need an isolation row, since none take a
      per-resource id in their path (org-wide aggregates, not a single
      resource lookup).

      Full backend suite (1228 tests, up from 1223), ruff, mypy clean;
      `test_matrix_covers_every_permission_gated_route`'s meta-assertion
      now passes with the new route represented.
- [x] Stage 3 — Frontend. New route `/reports`: client-rendered (not
      server-rendered like `/dashboard`) — the Project section's four
      list states need to be MSW-testable, the same reasoning
      `team/page.tsx`'s own departure from ARCHITECTURE.md §5's default
      already established. Three independent `useQuery` calls
      (`fetchProjectAnalytics`/`fetchLeadStats`/`fetchFinanceStats`, no
      new endpoint needed beyond Stage 1's). **Company** (headline
      numbers combining one figure from each of the other three, no
      metric of its own — decision 1); **Project** (org-wide headline
      numbers + the per-project breakdown table, the one section with
      real loading/error/empty/populated states); **Sales** (pipeline
      value, conversion rate, follow-ups due); **Finance** (reuses
      `finance/page.tsx`'s own plain-text-row rendering for `revenue_
      trend`/`expense_breakdown` verbatim — no charting library, per the
      confirmed scope decision). Finance section rendered only when its
      own query has data — omitted, not shown as "—", for MEMBER/MANAGER.
      `sidebar.tsx`'s existing disabled "Reports" placeholder flipped to
      a real `href`, no `restrictedToAdminPlus` flag.

      5 new component tests (`tests/reports.test.tsx`): loading, full
      OWNER-view populated state (all four sections, percentages
      correctly formatted), MEMBER/MANAGER view (Finance section
      correctly absent), empty-projects state, error state. Plus
      `sidebar.test.tsx` implicitly covered by the existing suite (no new
      case needed — Reports isn't role-restricted, so no analogous "hides
      for MEMBER" test the way Finance's own sidebar test needed).
      `pnpm typecheck`/`lint`/`prettier`/`test`/`build` all green (94
      frontend tests, up from 89).

      **Caught by the manual walkthrough, not by any automated test**: the
      first version gated the whole page's loading/error state on *all
      three* queries (`isLoading = projectAnalytics.isLoading ||
      leadStats.isLoading || financeStats.isLoading`). react-query's
      default retry behavior (3 retries, exponential backoff — this app's
      `QueryProvider` sets no custom retry policy) means an *expected*
      403 from `financeStats` for a MEMBER/MANAGER kept retrying for
      several seconds, and the combined gate kept the *entire* page stuck
      on the loading skeleton that whole time — Company/Project/Sales
      never appeared even though their own queries had already succeeded.
      MSW-backed component tests never caught this because MSW responds
      immediately and the test `QueryClient` sets `retry: false`; only a
      real browser against a real backend reproduced the delay. Fixed by
      gating the page's loading/error state on `projectAnalytics` alone
      (the one section everyone with `PROJECT_READ` is guaranteed);
      `leadStats`/`financeStats`-derived tiles already degrade
      gracefully (`?? "—"`, or omitted entirely for Finance) regardless of
      whether they're still pending or have errored, so decoupling the
      gate cost nothing.

      Manual `make dev` walkthrough (real Chromium, the project's own
      bundled browser via a throwaway script — same as Phase 6's own
      approach) as both MEMBER (`developer@trinolit.com`) and OWNER
      (`founder@trinolit.com`): confirmed Company/Project/Sales render
      for both, Finance renders only for OWNER. Independently verified
      two figures against a `psql` hand-count scoped to the correct
      organization (a first attempt without the org scope gave a
      misleading mismatch, caught and corrected before trusting the
      result): task completion `3/11 = 27%` and lead conversion
      `2/3 = 67%` both matched the rendered page exactly. `.env`/`apps/
      web/.env.local` reverted, scratch scripts deleted, both dev servers
      stopped.
- [x] Stage 4 — Final verification. **One seed script change was needed
      after all** — the plan's own exit criterion ("existing seed data
      already produces non-zero, non-trivial figures for every new
      metric") was verified directly rather than assumed, and turned out
      to be wrong for one metric: `scripts/seed.py`'s `_SeedTask`
      dataclass had no `due_date` field at all, so **zero** seed project
      tasks could ever be overdue — `overdue_tasks_count` would read `0`
      from a genuinely fresh seed, not the non-trivial figure the plan
      claimed. Fixed by adding an optional `due_date` to `_SeedTask`
      (computed relative to `date.today()` at seed time, same reasoning
      invoices' own one deliberately-overdue SENT invoice already uses —
      Phase 5 Stage 12) and setting one existing TODO task ("Set up
      hosting and domain") 3 days overdue. Threaded through `_ensure_
      task`'s `Task(...)` construction and `test_seed_idempotent.py`'s
      `_isolated_seed` fixture's own `_SeedTask` reconstruction (which
      would otherwise have silently dropped the new field for its own
      shadow tasks).

      Confirmed the rest of the plan's claim directly and it held: seed
      tasks already span `TODO`/`IN_PROGRESS`/`REVIEW`/`DONE`/`CANCELLED`
      across both seed projects, and seed leads already include one `WON`
      and one `LOST` entry — both exercise decisions 2/4 without any
      further change.

      Verified against the real local dev database (not just tests):
      deleted the one affected task, ran `make seed` twice (idempotent —
      re-running didn't duplicate it), confirmed via `psql` — scoped to
      the correct organization, the same lesson Stage 3's own walkthrough
      already learned the hard way — that `overdue_tasks_count` moved
      from 1 (previously accumulated dev-DB test debris, not reliable)
      to 2 (1 debris + 1 real seed row), proving the metric is now
      genuinely non-zero from the seed data itself.

      No new E2E flow (decision 5, explicitly re-confirmed here, not
      silently skipped) — Reports has no mutation to exercise.

      **Codex P1 (Stage 4 review)**: the manual verification above
      deleted the pre-existing task before re-seeding, which masked a
      real bug — `_ensure_task`'s get-or-create returns immediately on a
      title match, so an organization already seeded before this stage
      would keep `due_date = NULL` on that row forever; `make seed`
      alone would never apply the new overdue date to a real developer's
      existing database. Fixed by backfilling: `_ensure_task` now sets
      `due_date` on the existing row only when it's currently unset,
      mirroring `_get_or_create_project`'s own `client_id` backfill
      precedent exactly (only ever fills an unset field, never overwrites
      one a later run's data — or a real user edit through the app —
      might disagree with). Added the exact regression test requested:
      seed once (fresh row, date set directly), manually null the date to
      simulate a pre-Stage-4 row, seed twice more, and confirm the date
      is backfilled with no duplicate row. Re-verified directly against
      the real local dev database this time without deleting anything
      first — manually nulled the same task's `due_date`, ran `make seed`
      twice, confirmed exactly one row with the date correctly restored
      both times. Full backend suite (1229 tests, up from 1228), ruff,
      mypy clean.

      Full `make check` green end to end (ruff, mypy, pytest, eslint,
      prettier, tsc, vitest, `next build`, openapi diff clean — no
      schema/route change this stage).
- [x] Codex audit — final phase-level audit found no P0/P1 findings: the
      analytics aggregates, repaired project-visibility filtering, matrix
      coverage, Reports UI, and seed overdue-task backfill are coherent
      and complete; the pre-existing seed-task upgrade path is idempotent
      with user-set dates preserved.
- [x] Resolve P0/P1 findings — both findings raised across the 4 stages
      (Stage 1's project-visibility leak, Stage 4's seed backfill gap)
      were resolved and re-verified before the final audit; none remain
      open.

Phase 7 is complete across all 4 planned stages — project/task analytics
(with the repaired ownership-visibility split), extended lead conversion
stats, unchanged finance stats reused as-is, the read-only Reports page,
security matrices, and idempotent seed data all verified. The phase-level
Codex audit found no P0/P1 findings, closing Phase 7, mirroring how
Phases 2-6 each closed.

## Phase 8 — AI

Status: **In progress.** Planned via a dedicated plan-mode session
(mirroring how Phases 3-7 each started); plan file:
`reactive-dreaming-lantern.md`.

MASTER_PROMPT §30 ("AI — Later") lists this phase's features as a bare
"Future" bucket with two hard rules that shape every stage: "Do not
make V1 dependent on an LLM" and "Do not let an LLM calculate
authoritative financial totals." §39's own Phase 8 entry sequences the
work explicitly: "Only after enough real company data exists. Start
with meeting summary/action extraction." No AI infrastructure existed
anywhere in the repo before this phase — no SDK dependency, no
`AI_*` permission, no ADR, no schema stub.

**User-confirmed decisions**: (1) LLM provider is **OpenAI** (chat
completions + embeddings); (2) RAG scope is **full vector RAG**
(real pgvector storage/embeddings/retrieval), with "Company assistant"
built as the chat UI on the same retrieval rather than a second data
source.

**Architecture**: a new `ai` module (ARCHITECTURE.md §3), following the
`documents`-module precedent exactly — `ai → meetings/crm/work/finance`
(read-only into finance), never the reverse. The hardest design problem
(a cross-module RAG index has no inherent concept of permissions) is
resolved two ways, detailed fully in the plan file: finance rows are
never embedded at all (the assistant's finance awareness is a separate,
already-permission-gated tool call, never a vector search — this is
also the concrete form of §30's "no LLM financial totals" rule), and
every other chunk's visibility is re-validated live against its source
module's own existing visibility rule at query time, never trusted from
cached metadata (arrives in Stage 4).

Almost no new `Permission` is needed — meeting summarization/action
extraction reuse `MEETING_WRITE_OWN`/`MEETING_READ` (same creator/
participant/MANAGER+ rule meeting decisions/actions already use), lead
scoring reuses `LEAD_READ`/`LEAD_WRITE`, project risk reuses
`PROJECT_READ` with Phase 7's own established ownership filter. Only
the company-assistant/search surface needs a genuinely new value
(`AI_ASSISTANT_USE`, arriving Stage 4).

Every LLM call happens synchronously inside the request an explicit
user action triggers (Summarize/Extract/Ask/Score) — the same pattern
this codebase already uses for PDF rendering and SMTP email. ADR-0010
("no Redis or worker in V1") is not revisited this phase; no queue, no
cron is introduced.

- [x] Stage 1 — AI client foundations + meeting summarization.
      New `modules/ai/` package (models.py, schemas.py, routes/,
      services/) — the first row in ARCHITECTURE.md's module table
      since `documents` (Phase 6), with the same "not platform, needs
      cross-module reads" reasoning. `AIClient` Protocol (`complete()`
      only this stage — `embed()` arrives in Stage 3 once RAG actually
      needs it); `OpenAIClient` (wraps `openai.AsyncOpenAI`);
      `FakeAIClient` (deterministic templated output, records every
      call); `get_ai_client()` dependency mirroring `platform/email/
      deps.py`'s `get_email_sender` exactly, lazy-initialized the same
      way `identity/firebase_verifier.py`'s `_get_app()` is — a missing
      `OPENAI_API_KEY` fails only an actual call, never app boot.
      `fake_ai_client` conftest fixture mirrors `fake_email_sender`;
      every test in the suite uses it, none calls the real API.

      `MeetingSummary` (1:1 with a meeting, regenerated in place, no
      history) + migration `0009_ai_meeting_summaries`; `summarize_
      meeting()`/`get_meeting_summary()` reuse `meeting_service`'s own
      `can_write_meeting`/`ensure_meeting_visible` — no new permission,
      no ownership-split of its own (RBAC.md's existing "Meeting edit"/
      "Meeting visibility" rules already cover this exactly, same as
      decisions/actions). Routes `POST/GET /meetings/{id}/summary`
      registered in the ownership-split matrix set (not the flat authz
      matrix), matching the existing meeting-decisions/actions
      precedent — visibility/edit are ownership rules, not a flat
      per-row permission check.

      `openai` added as a dependency (`pyproject.toml`); `OPENAI_API_
      KEY`/`OPENAI_CHAT_MODEL` (default `gpt-4o-mini`)/`OPENAI_
      EMBEDDING_MODEL` (default `text-embedding-3-small`, declared now
      though unused until Stage 3 — one env-var pass, not two) added to
      `.env`/`.env.example`/`core/config.py`. `migrations/env.py` needed
      one addition (`from trinol.modules.ai import models`) so
      `alembic check`'s autogenerate diffing actually sees the new
      table — caught immediately by running `alembic check` itself
      after the first migration, before any review round.

      10 new integration tests (`test_meeting_summaries.py`): creator/
      MANAGER+ can summarize, a non-creator MEMBER cannot (403), GET
      before generation is 404, a participant can view but not
      generate, regenerating replaces content in place without
      duplicating the row, a feed event is recorded, and cross-org
      summary/POST are 404 (pre-seeding a real summary row first, so
      the 404 proves isolation rather than merely "not summarized
      yet" — the same subtlety the shared isolation-matrix row below
      also has to account for). The two new routes also added to
      `test_isolation_matrix.py`'s `_MEETING_CONTENT_ISOLATION_ROUTES`
      (parametrized across every role, not just one), and a new
      `make_meeting_summary` test factory.

      Full backend suite (1249 tests, up from 1229), ruff, mypy,
      `alembic check`, `make openapi` clean; `next build`/tsc/vitest
      clean (no frontend UI yet — that's Stage 2).
- [x] Stage 2 — Action extraction + meetings frontend.
      `MeetingAction.source` (`HUMAN|AI`, default `HUMAN`) added via a
      `meetings`-owned migration (`0010_meeting_action_source`) — a
      normal schema evolution of `meetings`' own table, not an `ai`-owned
      write (ADR-0014).

      `ai.services.action_extraction_service.extract_actions()` lives in
      `ai`, not `meetings` (plan §0(c)): one transaction, inline
      `MeetingAction(...)` construction (never via `meetings`' own
      auto-committing `create_action`), reusing `can_write_meeting`'s
      exact creator-or-MANAGER+ rule — no new permission. Parses the
      model's response line-by-line (not JSON — far more robust to real
      model output variance, and just as easy to cap), stripping a
      leading bullet/number marker per line, capped at 10 suggestions
      regardless of how many lines come back. No owner/due_date is
      guessed; a human reviews/edits/deletes suggestions through the
      pre-existing action-item UI, no new review/approve flow.

      Route `POST /meetings/{id}/actions/extract` registered in the
      ownership-split matrix set, same as decisions/actions/summary.
      `FakeAIClient` gained a `next_response` test seam (returns a set
      string verbatim instead of the default template) — needed to
      actually exercise the 10-item cap with more than 10 fake lines.

      Frontend: a "Summarize"/"Regenerate summary" button + panel added
      to the meeting detail page's Notes tab (`retry: false` on the
      summary query — a fresh meeting's expected 404 must not hit
      react-query's default 3-retry backoff, the same lesson Phase 7
      Stage 3's stuck-loading bug already taught this app); an "Extract
      actions" button added to the Action Items tab, with a small "AI"
      badge on extracted rows.

      7 new backend integration tests (creator/non-creator, the 10-item
      cap with 30 fake lines, bullet/number-marker parsing, zero
      suggestions creates no rows/feed event, an extracted action
      deletable through the existing DELETE endpoint with no new code
      path, cross-org 404). Two new frontend component tests (generate a
      summary from the Notes tab; extract actions and see the AI badge).
      Both new routes added to `test_isolation_matrix.py`'s
      `_MEETING_CONTENT_ISOLATION_ROUTES` too.

      Full backend suite (1261 tests, up from 1249), ruff, mypy, `alembic
      check`, `make openapi` clean; frontend tsc/eslint/prettier/vitest
      (96 tests, up from 94)/`next build` clean.
- [x] Stage 3 — RAG infrastructure (no user-facing feature yet).
      **Real infra gap found and fixed, not assumed**: `pgvector` is not
      a "trusted" Postgres extension — confirmed directly against a real
      Postgres that `trinol_migrator` (which merely owns the database)
      gets a permission error trying to `CREATE EXTENSION vector`
      itself, unlike `citext`. Fixed at the provisioning layer, not the
      migration: `docker-compose.yml` and CI both switch from
      `postgres:16-alpine` to `pgvector/pgvector:pg16` (a drop-in
      `postgres:16` with pgvector built in), and
      `infrastructure/postgres/init.sql` — which already runs as a
      superuser at provisioning time, before any migration — installs
      the extension there, so the migration's own `CREATE EXTENSION IF
      NOT EXISTS vector` is always a no-op by the time it runs.
      DEPLOYMENT.md and ADR-0014 both updated; production's managed
      Postgres needs an admin to enable the extension the same way.

      `KnowledgeChunk` (+ `KnowledgeSourceType` enum: `MEETING|LEAD|
      PROJECT|TASK` — deliberately no `FINANCE` member, ADR-0014 §0(b))
      + migration `0011_ai_knowledge_chunks`, including an HNSW cosine-
      distance index declared in the ORM model's own `__table_args__`
      (`postgresql_using="hnsw"`/`postgresql_ops`) rather than left as
      migration-only raw SQL, so `alembic check` can actually verify it
      like every other index in this codebase.

      `AIClient.embed()` added to the Protocol/both implementations;
      `FakeAIClient` embeds deterministically (SHA-256 of the text, no
      network) so same-text/different-text produces the same/different
      vector reliably in tests, plus a `next_embedding` seam for Stage
      4's ranking tests. `embedding_service.chunk_and_embed()` (one
      chunk per source row — no real text splitter needed at this data
      volume) and `reindex_stale()` (bounded `max_sources`, org-wide scan
      across all four source types, embeds only rows with no chunk yet
      or a newer `updated_at` than the cached chunk's). `POST /ai/
      reindex` (reuses `ORG_SETTINGS_WRITE`'s ADMIN+ tier, not a new
      permission) as the manual recovery/backfill trigger only — nothing
      requires it for correctness yet, since nothing calls
      `reindex_stale` automatically until Stage 4's retrieval does.

      5 new integration tests: one chunk per seeded meeting/lead/project;
      only the row that actually changed gets re-embedded (a real
      trigger-driven timestamp comparison doesn't work inside one test's
      wrapping transaction — Postgres's `now()` is the *transaction*
      timestamp, frozen for the whole test, confirmed directly rather
      than assumed — so the test backdates the cached chunk's own
      `source_updated_at` instead, exercising the same comparison
      branch); the `max_sources` budget is respected; the reindex route
      403s below ADMIN. Full backend suite (1271 tests, up from 1261),
      ruff, mypy, `alembic check`, `make openapi` clean; no frontend
      change this stage.
- [x] Stage 4 — Company assistant + semantic search + retrieval filter.
      `retrieval_service.search_knowledge()`: over-fetches candidates by
      cosine distance (`limit * 5` — pgvector has no concept of
      permissions, so more are requested than needed), calls
      `embedding_service.reindex_stale()` first (self-healing, bounded,
      no write-hooks in the other four modules), then drops any
      candidate whose live source is no longer visible — re-fetching and
      re-running that module's own existing rule per type: `meeting_
      service.ensure_meeting_visible` for meetings, `project_service.
      ensure_project_visible` **plus an `archived_at` check** for
      projects (a gap the plan itself hadn't spelled out: an archived
      project's chunk would otherwise never be dropped, since `reindex_
      stale`'s own indexing query already excludes archived rows from
      being *re-embedded*, but never removes an already-indexed one —
      caught and fixed while implementing, not left as a latent leak);
      leads/tasks re-check only existence/archival, never a permission,
      per RBAC.md's own documented no-ownership-split rule for both.

      `assistant_service.ask()`: retrieval, plus a finance tool call
      (`finance.services.dashboard_service.get_finance_stats`, invoked
      only when `Permission.FINANCE_READ in ROLE_PERMISSIONS[actor.
      role]`) injected into the prompt as a labeled "VERIFIED FINANCIAL
      DATA" block the system prompt is told never to alter — the
      concrete, mechanical form of MASTER_PROMPT §30's "no LLM financial
      totals" rule, not just a convention.

      New `Permission.AI_ASSISTANT_USE` (MEMBER-tier — RBAC.md §2/§3
      updated) — the one genuinely new permission this whole phase
      needs, since there's no single existing resource to hang it on;
      the real restriction lives in the retrieval filter, not the route
      gate, same "broad route, narrow service" shape `TASK_WRITE_OWN`
      already uses. Routes `GET /ai/search`, `POST /ai/assistant/ask`
      added to the flat authz matrix (no ownership-split row needed —
      the filter is internal to the service, covered by its own
      dedicated test file, same reasoning `/leads/stats`/`/projects/
      analytics` already established).

      Frontend: new `/assistant` chat page (plain local state, no
      react-query — a one-shot ask/answer exchange, not a cacheable
      list) added to the sidebar's INSIGHTS group.

      **The load-bearing test of the whole phase**
      (`test_company_assistant.py`, 5 tests): forces `fake_ai_client.
      next_embedding` to an identical fixed vector for every chunk and
      every query, so a MANAGER-only-visible project's chunk ties for
      closest match — proving it's excluded from a MEMBER's `/ai/search`
      results by the permission filter alone, not by incidental low
      similarity ranking; confirms a MANAGER *does* see it (the filter
      isn't just "always exclude"); confirms a MEMBER's assistant prompt
      never contains the `VERIFIED FINANCIAL DATA` block or the actual
      figure, while an OWNER's does, verbatim. One frontend component
      test file (3 tests): empty state, ask/answer/source-count render,
      error state.

      Full backend suite (1286 tests, up from 1271), ruff, mypy,
      `alembic check`, `make openapi` clean; frontend tsc/eslint/
      prettier/vitest (99 tests, up from 96)/`next build` clean.
- [ ] Stage 5 — Lead scoring
- [ ] Stage 6 — Project risk intelligence
- [ ] Stage 7 — Security matrices, RBAC.md, seed data, E2E
- [ ] Stage 8 — AI audit
- [ ] Codex audit
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

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

Status: **Implementation plan approved (11 stages). Stages 1-2 complete.**
Stage 3 (Lead CRUD + stage transitions) is next.

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

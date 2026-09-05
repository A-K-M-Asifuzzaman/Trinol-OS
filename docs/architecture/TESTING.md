# Trinol OS — Testing Architecture

## 1. Principle

Test the invariants that would hurt if broken: authorization, organization
isolation, money, and state transitions. Do not chase a coverage number — a
suite of assertions on getters is cost with no signal.

Never skip, `xfail` or delete a failing test to make CI green. A failing test is
either a real defect or a wrong test; both need a decision, not a mute button.

## 2. Backend

`pytest` + `pytest-asyncio`, `httpx.AsyncClient` against the real app.

- **Database**: a real PostgreSQL 16 (service container in CI, compose locally).
  Not SQLite — the schema depends on citext, native enums, `jsonb`, `numeric`
  and check constraints, and a SQLite suite would pass while production breaks.
- **Isolation**: migrations run once per session; each test runs in a
  transaction that is rolled back. Tests never see each other's rows.
- **Factories**: plain factory functions per entity (`make_task(...)`),
  not `factory_boy`. Two orgs and one user per role are built by fixtures, since
  almost every security test needs exactly that.
- **Layers**:
  - unit — permission map, invoice arithmetic, project progress, invoice-number
    generation, state-transition rules. No database.
  - integration — route through service to database, real HTTP, real auth.
  - security — the matrices in §4.

## 3. Frontend

- `vitest` + React Testing Library. Test behaviour through the DOM the user
  sees; no snapshot tests of whole trees, no assertions on internal state.
- API calls mocked with MSW at the network boundary, so the code under test is
  the real fetch path.
- Required per feature: loading, empty, error and populated states of every list
  view; form validation messages; a keyboard path through any custom widget.

## 4. Security suites (non-negotiable)

Four table-driven matrices, each failing loudly when a new route is not
represented:

1. **Authentication** — every non-public route without a session → `401`.
2. **Authorization** — every route × every role × own/other/other-org resource
   → expected status ([RBAC.md §6](RBAC.md#6-testing)).
3. **Isolation** — every org-scoped route, member of org B against a resource in
   org A → `404`, never `403` and never `200`.
4. **Escalation** — the six guards in [RBAC.md §5](RBAC.md#5-escalation-guards),
   including the concurrent last-owner demotion.
5. **Schema integrity** — one test reads `information_schema` against the
   migrated database and asserts that every FK between two org-scoped tables is
   composite, and that every table targeted by one carries its
   `UNIQUE (organization_id, id)`
   ([DATABASE.md §5.1](DATABASE.md#51-cross-organization-relationship-integrity)).
   A single-column FK to an org-scoped table fails the suite. This is what stops
   the rule from decaying: a plain `ForeignKey("projects.id")` is the natural
   thing to type, and review will not reliably catch it.

## 5. End-to-end

Playwright, Chromium, against the docker-compose stack with seeded data.
Introduced in Phase 2 when there is a flow worth driving, not in Phase 1.

Scope is deliberately small — the eight flows from the spec (login, create lead,
convert lead, create project, create task, move task on the board, create
client, create invoice). E2E is the most expensive and flakiest layer; it covers
the happy paths that must never break, and nothing else.

## 6. CI gates

Every pull request, all blocking:

```
ruff check + ruff format --check
mypy (strict on apps/api/src)
pytest (unit + integration + security)
alembic upgrade head on an empty DB, then downgrade -1 && upgrade head
alembic check (models vs migration head)
eslint + prettier --check
tsc --noEmit
vitest
next build
gitleaks, pip-audit, npm audit
```

Playwright runs on the main branch and on release candidates, not on every PR.

## 7. Definition of tested

A phase is not complete until: every new endpoint appears in the authorization
and isolation matrices; every state machine has a test for one illegal
transition; every money calculation has a test with a value that exposes
rounding (e.g. `33.33 × 3`); and every new list view has its four UI states
tested.

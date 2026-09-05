# ADR-0003 — Organization isolation via a single scoped-session choke point

Status: Accepted (Phase 0)

## Context

MASTER_PROMPT §26 requires Organization to be first-class from day one and
warns against a design that forces rewriting every query later. V1 has exactly
one organization, so isolation bugs would be **invisible in production** until
the second tenant arrives — the worst possible failure timing.

## Decision

Single database, single schema, `organization_id` on every business table.
Enforcement at one place in the application, plus a runtime guard:

1. Org-scoped models inherit an `OrgScoped` base carrying the FK.
2. Services receive an `OrgSession`, never a raw `AsyncSession`. Its `select()`
   injects the org predicate; its `add()` stamps `organization_id`.
3. A SQLAlchemy `before_execute` hook raises if a statement touches an
   `OrgScoped` table with no `organization_id` predicate. **Enabled in every
   environment**, not only tests.
4. A cross-org test matrix hits every org-scoped route as a member of another
   org and asserts `404`.

## Alternatives rejected

**PostgreSQL row-level security.** Genuinely the strongest option and the one to
adopt at V4. Deferred because it needs a per-transaction `SET LOCAL` of the
tenant id that must survive connection pooling, a non-owner application role
(policies do not apply to the table owner or to `BYPASSRLS`), and it makes
migrations and debugging materially harder. The schema designed here is exactly
the schema RLS needs, so adopting it later is adding policies, not a redesign.

**Schema-per-tenant / database-per-tenant.** Migration cost multiplies by tenant
count and cross-tenant reporting becomes painful. Wrong shape for a product
aimed at many small teams.

**Nothing but discipline and code review.** This is the option most projects
take by accident, and it is why cross-tenant leaks are the most common
multi-tenant bug. Rejected explicitly.

## Consequences

- One filter to get right instead of several hundred.
- Guard cost is one predicate walk per statement; negligible next to the query.
- A deliberate cross-org read (future admin tooling) needs an explicit,
  greppable escape hatch — `unscoped()` — which is exactly the audit surface
  wanted.
- Risk accepted: the guard checks that a predicate exists, not that its value is
  correct. The test matrix covers the value.

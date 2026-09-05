# ADR-0004 — Roles and permissions as code, not database rows

Status: Accepted (Phase 0)

## Context

MASTER_PROMPT §18 defines four fixed roles and asks for centralized
authorization. §25's candidate entity list includes `Role` and `Permission`
tables.

## Decision

`Role` is a Python enum. `ROLE_PERMISSIONS: dict[Role, frozenset[Permission]]`
is a static map. No `roles` table, no `permissions` table, no
`role_permissions` join. A membership row stores the role as a native enum
column.

Enforcement is one FastAPI dependency, `require(Permission.X)`, plus resource
predicates in services. A startup check fails the boot if any route declares
neither a permission nor `@public`.

## Alternatives rejected

**Database-driven permissions.** Justified when customers define custom roles.
Nothing in the V1 or V2 product does — there is no UI for it and no requirement
for one. Building it now means a configuration surface with no configurator, a
join on every request, migrations to change a permission, and permission logic
that cannot be read by reading the code. It is the textbook case of the
flexibility that never gets used.

**Casbin or a policy engine.** A dependency and a second policy language for
four roles and roughly thirty permissions.

**Role checks scattered at call sites** (`if user.role == "ADMIN"`). Explicitly
warned against by the spec, and unauditable.

## Consequences

- The whole authorization model is one readable file, diffable in review.
- Changing a permission is a code change with a test — which is correct for
  security-relevant configuration.
- Custom roles at V4 mean adding tables that *override* the static map, with
  the map as the default. The `Permission` vocabulary survives that change.

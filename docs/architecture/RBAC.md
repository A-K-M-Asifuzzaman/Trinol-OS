# Trinol OS — Authorization

Decision record: [ADR-0004](../adr/0004-roles-as-code.md).

## 1. Model

Two layers, both server-side:

1. **Role permissions** — what a role may do to a *type* of thing.
2. **Resource rules** — whether this user may touch *this* row.

Roles are a Python enum and a static permission map in
`core/authz/permissions.py`. There is no `roles` table and no `permissions`
table in V1: nothing in the product lets an admin define a custom role, so a
database-driven permission system would be a configuration surface with no
configurator, plus a join on every request.

```python
class Role(StrEnum):
    OWNER = "OWNER"; ADMIN = "ADMIN"; MANAGER = "MANAGER"; MEMBER = "MEMBER"

ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {...}
```

Roles are cumulative: `MEMBER ⊂ MANAGER ⊂ ADMIN ⊂ OWNER`. That is asserted by a
test, so a hand-edit to the map cannot quietly break the hierarchy.

## 2. Permission matrix

| Area | MEMBER | MANAGER | ADMIN | OWNER |
|---|---|---|---|---|
| View projects/tasks in own org | ✓ | ✓ | ✓ | ✓ |
| Create/edit own tasks | ✓ | ✓ | ✓ | ✓ |
| Edit any task | – | ✓ | ✓ | ✓ |
| Create/edit projects | – | ✓ | ✓ | ✓ |
| Delete project | – | – | ✓ | ✓ |
| Leads & clients: view | ✓ | ✓ | ✓ | ✓ |
| Leads & clients: create/edit | – | ✓ | ✓ | ✓ |
| Convert lead | – | ✓ | ✓ | ✓ |
| Meetings: create/edit own | ✓ | ✓ | ✓ | ✓ |
| Finance: view | – | – | ✓ | ✓ |
| Income/expenses: write | – | – | ✓ | ✓ |
| Invoices: create/send | – | – | ✓ | ✓ |
| Invoice: cancel | – | – | ✓ | ✓ |
| Record payment | – | – | ✓ | ✓ |
| Team: view | ✓ | ✓ | ✓ | ✓ |
| Invite member | – | – | ✓ | ✓ |
| Change member role | – | – | ✓* | ✓ |
| Remove member | – | – | ✓* | ✓ |
| Assign OWNER / ADMIN role | – | – | – | ✓ |
| Org settings | – | – | ✓ | ✓ |
| Delete organization | – | – | – | ✓ |
| Audit log | – | – | ✓ | ✓ |

`*` ADMIN may only act on MANAGER and MEMBER (see §5).

Finance is invisible to MEMBER and MANAGER — not merely hidden in navigation.
The endpoints return `403`, and the dashboard's finance widgets are omitted from
the API response rather than filtered in the browser.

## 3. Enforcement

One dependency, used on every non-public route:

```python
@router.post("/projects", dependencies=[Depends(require(Permission.PROJECT_WRITE))])
```

A route with no `require(...)` and no explicit `@public` marker fails a startup
check that walks the router table. This is the single most valuable guard in the
system: it makes "forgot to add authorization" a boot failure instead of a
vulnerability.

Resource rules live in services, not routes, expressed as small predicates:

- Task edit: `MANAGER+` **or** `task.assignee_id == user.id` **or**
  `task.created_by == user.id`.
- Project detail: `MANAGER+` **or** membership in `project_members`.
- Comment edit/delete: author only (`ADMIN+` may delete).
- Meeting edit: creator or `MANAGER+`.

## 4. Not-found over forbidden

A resource belonging to another organization returns **404**, never 403. A 403
confirms the id exists. Within your own org, a permission failure returns 403,
which is honest and useful.

## 5. Escalation guards

Explicit rules, each with a regression test:

1. Nobody may change their own role.
2. Only OWNER may grant or revoke `OWNER` or `ADMIN`.
3. ADMIN may not modify or remove an OWNER or another ADMIN.
4. The **last remaining OWNER** cannot be demoted, removed, or deactivated.
   Enforced in a transaction that takes `SELECT … FOR UPDATE` on the
   organization row, so two concurrent demotions cannot both pass the check.
5. Role changes revoke the target user's other sessions, so a demotion takes
   effect immediately rather than at their next login.
6. Every role change, member removal and permission-relevant settings change
   writes an `is_audit` activity event.

## 6. Testing

Authorization is tested as a matrix, not as scattered assertions:
for every route × every role × (own resource, other's resource, other org's
resource), assert the expected status. The table lives in
`tests/security/test_authz_matrix.py`; a new route with no row in it fails the
suite.

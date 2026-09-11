from __future__ import annotations

from enum import StrEnum


class Role(StrEnum):
    """The org role stored on `memberships.role` (DATABASE.md §3) — defined
    here, not in modules/identity/models.py, because it's equally an authz
    concept and an identity one; one enum, not two sources of truth for the
    same four values."""

    OWNER = "OWNER"
    ADMIN = "ADMIN"
    MANAGER = "MANAGER"
    MEMBER = "MEMBER"


class Permission(StrEnum):
    """RBAC.md §2's full matrix, defined now rather than incrementally per
    phase (ADR-0004): it's one static file, and the cumulative-hierarchy test
    below wants the whole map anyway. Only the TEAM_* values are consumed by
    any route in Phase 1 — the rest sit unused until their phase, same as the
    Task/Invoice status enum values already do."""

    # Work — Phase 2
    PROJECT_READ = "PROJECT_READ"
    TASK_READ = "TASK_READ"
    TASK_WRITE_OWN = "TASK_WRITE_OWN"
    TASK_WRITE_ANY = "TASK_WRITE_ANY"
    PROJECT_WRITE = "PROJECT_WRITE"
    PROJECT_DELETE = "PROJECT_DELETE"
    # MEMBER-tier, route-reachability only (RBAC.md §3, ROADMAP.md Phase 2
    # decision 6): gates project-member-management routes for everyone, same
    # shape as TASK_WRITE_OWN vs TASK_WRITE_ANY. The service checks the real
    # rule (PROJECT_WRITE i.e. MANAGER+, OR project.owner_id == user.id).
    PROJECT_MEMBER_WRITE = "PROJECT_MEMBER_WRITE"

    # CRM — Phase 3
    LEAD_READ = "LEAD_READ"
    CLIENT_READ = "CLIENT_READ"
    LEAD_WRITE = "LEAD_WRITE"
    CLIENT_WRITE = "CLIENT_WRITE"
    LEAD_CONVERT = "LEAD_CONVERT"

    # Meetings — Phase 4
    MEETING_READ = "MEETING_READ"
    MEETING_WRITE_OWN = "MEETING_WRITE_OWN"

    # Documents — Phase 6
    DOCUMENT_READ = "DOCUMENT_READ"
    DOCUMENT_WRITE = "DOCUMENT_WRITE"

    # Finance — Phase 5
    FINANCE_READ = "FINANCE_READ"
    FINANCE_WRITE = "FINANCE_WRITE"
    INVOICE_WRITE = "INVOICE_WRITE"
    INVOICE_CANCEL = "INVOICE_CANCEL"
    PAYMENT_WRITE = "PAYMENT_WRITE"

    # Team — Phase 1
    TEAM_READ = "TEAM_READ"
    MEMBER_INVITE = "MEMBER_INVITE"
    MEMBER_ROLE_WRITE = "MEMBER_ROLE_WRITE"
    MEMBER_REMOVE = "MEMBER_REMOVE"

    # Organization
    ORG_SETTINGS_WRITE = "ORG_SETTINGS_WRITE"
    ORG_DELETE = "ORG_DELETE"

    # Audit
    AUDIT_READ = "AUDIT_READ"


# Each tier is built as an explicit superset of the one below it, so the
# cumulative hierarchy (RBAC.md §1: MEMBER ⊂ MANAGER ⊂ ADMIN ⊂ OWNER) holds by
# construction — test_permission_hierarchy.py still asserts it, guarding
# against a future hand-edit that breaks the union relationship.
_MEMBER: frozenset[Permission] = frozenset(
    {
        Permission.PROJECT_READ,
        Permission.PROJECT_MEMBER_WRITE,
        Permission.TASK_READ,
        Permission.TASK_WRITE_OWN,
        Permission.LEAD_READ,
        Permission.CLIENT_READ,
        Permission.MEETING_READ,
        Permission.MEETING_WRITE_OWN,
        Permission.DOCUMENT_READ,
        Permission.TEAM_READ,
    }
)

_MANAGER: frozenset[Permission] = _MEMBER | frozenset(
    {
        Permission.TASK_WRITE_ANY,
        Permission.PROJECT_WRITE,
        Permission.LEAD_WRITE,
        Permission.CLIENT_WRITE,
        Permission.LEAD_CONVERT,
        Permission.DOCUMENT_WRITE,
    }
)

_ADMIN: frozenset[Permission] = _MANAGER | frozenset(
    {
        Permission.PROJECT_DELETE,
        Permission.FINANCE_READ,
        Permission.FINANCE_WRITE,
        Permission.INVOICE_WRITE,
        Permission.INVOICE_CANCEL,
        Permission.PAYMENT_WRITE,
        Permission.MEMBER_INVITE,
        Permission.MEMBER_ROLE_WRITE,
        Permission.MEMBER_REMOVE,
        Permission.ORG_SETTINGS_WRITE,
        Permission.AUDIT_READ,
    }
)

_OWNER: frozenset[Permission] = _ADMIN | frozenset({Permission.ORG_DELETE})

ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.MEMBER: _MEMBER,
    Role.MANAGER: _MANAGER,
    Role.ADMIN: _ADMIN,
    Role.OWNER: _OWNER,
}

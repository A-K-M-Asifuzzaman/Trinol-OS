from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import Depends

from trinol.core.authz.permissions import ROLE_PERMISSIONS, Permission
from trinol.core.errors import ForbiddenError
from trinol.modules.identity.deps import get_current_membership
from trinol.modules.identity.models import Membership

_PUBLIC_MARKER = "__trinol_public__"
_REQUIRES_MARKER = "__trinol_requires_permission__"


def public[F: Callable[..., object]](func: F) -> F:
    """Marks a route as deliberately exempt from the require(...) mandate
    (RBAC.md §3) — checked by core/authz/startup_audit.py. Not necessarily
    unauthenticated: logout (DELETE /api/v1/auth/session) is authenticated
    via get_current_session but self-service, with no role-based permission
    to check; /health and /ready need no authentication at all. Both kinds
    belong here — @public means "no Permission gate", not "no auth"."""
    setattr(func, _PUBLIC_MARKER, True)
    return func


def is_public(endpoint: Callable[..., object]) -> bool:
    return bool(getattr(endpoint, _PUBLIC_MARKER, False))


def get_required_permission(dependency: Callable[..., object]) -> Permission | None:
    """Reads the marker `require()` stamps on its closure. Shared by
    startup_audit.py's boot-time check (only needs to know one exists) and
    the security-matrix tests (need the actual Permission, to know which
    roles a route should 403 for) — one place reading the marker instead of
    two modules each duplicating the constant."""
    return getattr(dependency, _REQUIRES_MARKER, None)


def require(permission: Permission) -> Callable[..., Awaitable[None]]:
    """`dependencies=[Depends(require(Permission.X))]` (RBAC.md §3). Checks
    role-level permission only — resource-level rules (e.g. "MANAGER+ or the
    task's own assignee") live in the service layer, not here."""

    async def _check(membership: Membership = Depends(get_current_membership)) -> None:
        if permission not in ROLE_PERMISSIONS[membership.role]:
            raise ForbiddenError(f"Missing required permission: {permission.value}")

    # A fresh closure every call, so startup_audit.py can't compare identity
    # against a fixed function — it checks this marker instead.
    setattr(_check, _REQUIRES_MARKER, permission)
    return _check

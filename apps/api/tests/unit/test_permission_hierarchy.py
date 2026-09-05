from __future__ import annotations

from trinol.core.authz.permissions import ROLE_PERMISSIONS, Role

# RBAC.md §1: "Roles are cumulative: MEMBER ⊂ MANAGER ⊂ ADMIN ⊂ OWNER. That is
# asserted by a test, so a hand-edit to the map cannot quietly break the
# hierarchy." Each tier is built as an explicit superset in permissions.py,
# so this holds by construction today — this test guards against a future
# hand-edit breaking that union relationship, not today's correctness.

_HIERARCHY = [Role.MEMBER, Role.MANAGER, Role.ADMIN, Role.OWNER]


def test_each_role_is_a_subset_of_the_next() -> None:
    # Deliberately zips lists of different lengths (consecutive-pairs idiom):
    # strict=False, not True.
    for lower, higher in zip(_HIERARCHY, _HIERARCHY[1:], strict=False):
        assert ROLE_PERMISSIONS[lower] <= ROLE_PERMISSIONS[higher], (
            f"{lower} must be a subset of {higher}"
        )


def test_owner_has_every_permission_any_role_has() -> None:
    all_permissions = frozenset().union(*ROLE_PERMISSIONS.values())
    assert ROLE_PERMISSIONS[Role.OWNER] == all_permissions


def test_member_has_the_fewest_permissions() -> None:
    member_count = len(ROLE_PERMISSIONS[Role.MEMBER])
    for role in _HIERARCHY[1:]:
        assert len(ROLE_PERMISSIONS[role]) >= member_count

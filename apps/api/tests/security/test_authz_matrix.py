from __future__ import annotations

import pytest
from fastapi.routing import APIRoute
from httpx import AsyncClient

from tests.factories import make_membership, make_project, make_user
from tests.helpers import login_as
from trinol.core.authz.permissions import ROLE_PERMISSIONS, Permission, Role
from trinol.core.authz.require import is_public
from trinol.core.authz.startup_audit import iter_api_routes
from trinol.main import app

# RBAC.md §6: for every route x every role x own resource, assert the
# expected status.

pytestmark = pytest.mark.usefixtures("db_session")


@pytest.mark.parametrize("role", [Role.OWNER, Role.ADMIN, Role.MANAGER, Role.MEMBER])
async def test_list_team_is_readable_by_every_role(
    client: AsyncClient, fake_verifier, db_session, role: Role
) -> None:
    await login_as(client, fake_verifier, db_session, role=role)
    response = await client.get("/api/v1/memberships")
    assert response.status_code == 200


@pytest.mark.parametrize("role", [Role.OWNER, Role.ADMIN, Role.MANAGER, Role.MEMBER])
async def test_get_team_member_is_readable_by_every_role(
    client: AsyncClient, fake_verifier, db_session, role: Role
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=role)
    response = await client.get(f"/api/v1/memberships/{actor.membership.id}")
    assert response.status_code == 200


@pytest.mark.parametrize(
    ("role", "expected_status"),
    [
        (Role.OWNER, 200),
        (Role.ADMIN, 200),
        (Role.MANAGER, 403),
        (Role.MEMBER, 403),
    ],
)
async def test_role_change_requires_admin_or_owner(
    client: AsyncClient, fake_verifier, db_session, role: Role, expected_status: int
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=role)
    target_user = await make_user(db_session, email=f"target-role-{actor.organization.id}@x.com")
    target = await make_membership(
        db_session, organization=actor.organization, user=target_user, role=Role.MEMBER
    )
    await db_session.commit()

    response = await client.patch(
        f"/api/v1/memberships/{target.id}",
        json={"role": "MANAGER"},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == expected_status


@pytest.mark.parametrize(
    ("role", "expected_status"),
    [
        (Role.OWNER, 200),
        (Role.ADMIN, 200),
        (Role.MANAGER, 403),
        (Role.MEMBER, 403),
    ],
)
async def test_removal_requires_admin_or_owner(
    client: AsyncClient, fake_verifier, db_session, role: Role, expected_status: int
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=role)
    target_user = await make_user(db_session, email=f"target-remove-{actor.organization.id}@x.com")
    target = await make_membership(
        db_session, organization=actor.organization, user=target_user, role=Role.MEMBER
    )
    await db_session.commit()

    response = await client.patch(
        f"/api/v1/memberships/{target.id}",
        json={"status": "INACTIVE"},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == expected_status


async def test_patch_rejects_role_and_status_together(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    """Codex Stage 9 review: role and status each map to their own
    lock+commit service call (change_role, remove_member). Accepting both in
    one PATCH ran them back to back with no shared transaction — if the
    second raised, the first's mutation was already durably committed while
    the client saw one failed request. Rejected at the schema now: exactly
    one of role/status, never both."""
    actor = await login_as(client, fake_verifier, db_session, role=Role.OWNER)
    target_user = await make_user(db_session, email=f"target-both-{actor.organization.id}@x.com")
    target = await make_membership(
        db_session, organization=actor.organization, user=target_user, role=Role.MEMBER
    )
    await db_session.commit()

    response = await client.patch(
        f"/api/v1/memberships/{target.id}",
        json={"role": "MANAGER", "status": "INACTIVE"},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == 422


async def test_patch_rejects_neither_role_nor_status(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.OWNER)
    target_user = await make_user(db_session, email=f"target-neither-{actor.organization.id}@x.com")
    target = await make_membership(
        db_session, organization=actor.organization, user=target_user, role=Role.MEMBER
    )
    await db_session.commit()

    response = await client.patch(
        f"/api/v1/memberships/{target.id}",
        json={},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == 422


# Stage 11: the formal matrix RBAC.md §6 asks for, plus the meta-assertion
# that "a new route with no row in it fails the suite" — one row per
# permission-gated route, with an example valid payload for the routes that
# need a body, so a role that legitimately holds the permission isn't
# rejected by request validation. {membership_id} is filled with a freshly
# created target membership per test, not the actor's own — PATCHing
# yourself hits change_role/remove_member's separate "can't act on your own
# membership" guard, which isn't what this matrix is testing.
_MATRIX_ROWS: list[tuple[str, str, Permission, dict[str, str] | None]] = [
    (
        "POST",
        "/api/v1/invitations",
        Permission.MEMBER_INVITE,
        {"email": "row@x.com", "role": "MEMBER"},
    ),
    ("GET", "/api/v1/invitations", Permission.MEMBER_INVITE, None),
    ("GET", "/api/v1/memberships", Permission.TEAM_READ, None),
    ("GET", "/api/v1/memberships/{membership_id}", Permission.TEAM_READ, None),
    (
        "PATCH",
        "/api/v1/memberships/{membership_id}",
        Permission.MEMBER_ROLE_WRITE,
        {"role": "MANAGER"},
    ),
    (
        "POST",
        "/api/v1/projects",
        Permission.PROJECT_WRITE,
        {"project_code": "MTX-1", "name": "Matrix Project"},
    ),
    ("GET", "/api/v1/projects", Permission.PROJECT_READ, None),
    (
        "PATCH",
        "/api/v1/projects/{project_id}",
        Permission.PROJECT_WRITE,
        {"name": "Matrix Renamed"},
    ),
    ("DELETE", "/api/v1/projects/{project_id}", Permission.PROJECT_DELETE, None),
]

# RBAC.md §3 / ROADMAP.md Phase 2 decision 6: these routes are gated at the
# route by a MEMBER-tier permission that only controls reachability — the
# real rule (MANAGER+ OR resource ownership/membership) lives in the
# service. The generic per-row assertion below ("permission in role <=> non
# -403") doesn't fit that shape: every role holds the route permission, so
# it would incorrectly assert a non-owner/non-member MEMBER must not be
# 403. These routes still need to appear here so the meta-assertion doesn't
# flag them as uncovered — the real (owner/member vs not) behavior is
# asserted by dedicated tests in test_projects.py/test_project_members.py,
# same dual-coverage pattern MEMBER_ROLE_WRITE's hand-written tests above
# already use alongside its own (non-split) matrix row.
_OWNERSHIP_SPLIT_ROUTES: set[tuple[str, str]] = {
    ("GET", "/api/v1/projects/{project_id}"),
    ("GET", "/api/v1/projects/{project_id}/members"),
    ("POST", "/api/v1/projects/{project_id}/members"),
    ("PATCH", "/api/v1/projects/{project_id}/members/{member_id}"),
    ("DELETE", "/api/v1/projects/{project_id}/members/{member_id}"),
}


def _live_permission_gated_routes() -> set[tuple[str, str]]:
    pairs: set[tuple[str, str]] = set()
    for route in iter_api_routes(app):
        if not isinstance(route, APIRoute) or is_public(route.endpoint):
            continue
        for method in route.methods or set():
            if method in ("HEAD", "OPTIONS"):
                continue
            pairs.add((method, route.path))
    return pairs


def test_matrix_covers_every_permission_gated_route() -> None:
    """RBAC.md §6: "a new route with no row in it fails the suite." Derives
    the live set of non-public routes from the app itself (the same markers
    core/authz/startup_audit.py's boot-time check reads), so a new route
    can't silently go untested the way a hand-maintained list with no
    cross-check against reality could."""
    matrix_routes = {(method, path) for method, path, _permission, _body in _MATRIX_ROWS}
    matrix_routes |= _OWNERSHIP_SPLIT_ROUTES
    missing = _live_permission_gated_routes() - matrix_routes
    assert not missing, f"Route(s) with no authz-matrix row: {sorted(missing)}"


@pytest.mark.parametrize("method,path,permission,body", _MATRIX_ROWS)
@pytest.mark.parametrize("role", list(Role))
async def test_matrix_row_respects_required_permission(
    client: AsyncClient,
    fake_verifier,
    db_session,
    role: Role,
    method: str,
    path: str,
    permission: Permission,
    body: dict[str, str] | None,
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=role)
    target_user = await make_user(db_session, email=f"matrix-target-{actor.organization.id}@x.com")
    target = await make_membership(
        db_session, organization=actor.organization, user=target_user, role=Role.MEMBER
    )
    await db_session.commit()

    resolved_path = path.replace("{membership_id}", str(target.id))
    if "{project_id}" in resolved_path:
        # Both rows using this placeholder (PATCH/DELETE project) are
        # MANAGER+-only with no ownership escape hatch, so who owns the
        # test project doesn't affect the assertion below.
        project = await make_project(db_session, organization=actor.organization, owner=target)
        await db_session.commit()
        resolved_path = resolved_path.replace("{project_id}", str(project.id))
    headers = {"X-CSRF-Token": actor.csrf_token} if method != "GET" else {}
    response = await client.request(method, resolved_path, json=body, headers=headers)

    if permission in ROLE_PERMISSIONS[role]:
        assert response.status_code != 403, (
            f"{role} unexpectedly forbidden on {method} {path}: {response.text}"
        )
    else:
        assert response.status_code == 403, (
            f"{role} unexpectedly allowed on {method} {path}: {response.text}"
        )

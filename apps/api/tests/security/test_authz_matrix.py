from __future__ import annotations

import pytest
from fastapi.routing import APIRoute
from httpx import AsyncClient

from tests.factories import (
    make_membership,
    make_organization,
    make_project,
    make_project_member,
    make_task,
    make_user,
)
from tests.helpers import login_as, login_as_existing
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
    (
        "POST",
        "/api/v1/projects/{project_id}/milestones",
        Permission.PROJECT_WRITE,
        {"name": "Matrix Milestone"},
    ),
    (
        "POST",
        "/api/v1/tasks",
        Permission.TASK_WRITE_OWN,
        {"title": "Matrix Task"},
    ),
    # RBAC.md §2 grants TASK_READ org-wide with no additional per-resource
    # restriction (unlike Project detail) — ROADMAP.md Stage 3 decision, so
    # every role is expected to pass both task-read rows below, same as the
    # team-read rows above.
    ("GET", "/api/v1/tasks", Permission.TASK_READ, None),
    ("GET", "/api/v1/tasks/{task_id}", Permission.TASK_READ, None),
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
    # Same shape (RBAC.md §3 "Project detail"): route is PROJECT_READ
    # (MEMBER-tier), service is ensure_project_visible (MANAGER+ or project
    # membership).
    ("GET", "/api/v1/projects/{project_id}/milestones"),
    # RBAC.md §3 "Task edit": route is TASK_WRITE_OWN (MEMBER-tier), service
    # is TASK_WRITE_ANY (MANAGER+) or assignee or creator. Delete follows
    # the same rule (task_service.can_write_task's docstring, ROADMAP.md
    # Stage 3 decision).
    ("PATCH", "/api/v1/tasks/{task_id}"),
    ("DELETE", "/api/v1/tasks/{task_id}"),
}


@pytest.mark.parametrize(
    ("method", "path_template", "body", "success_status"),
    [
        ("GET", "/api/v1/projects/{project_id}/members", None, 200),
        (
            "POST",
            "/api/v1/projects/{project_id}/members",
            {"user_id": "{add_user_id}"},
            201,
        ),
        (
            "PATCH",
            "/api/v1/projects/{project_id}/members/{member_id}",
            {"role_on_project": "LEAD"},
            200,
        ),
        ("DELETE", "/api/v1/projects/{project_id}/members/{member_id}", None, 204),
    ],
)
@pytest.mark.parametrize(
    ("access", "expected_status"),
    [("manager", None), ("owner", None), ("non_owner", 403), ("cross_org", 404)],
)
async def test_project_member_routes_enforce_ownership_split(
    client: AsyncClient,
    fake_verifier,
    db_session,
    method: str,
    path_template: str,
    body: dict[str, str] | None,
    success_status: int,
    access: str,
    expected_status: int | None,
) -> None:
    org = await make_organization(db_session)
    owner_user = await make_user(db_session, email=f"matrix-owner-{org.id}@x.com")
    owner = await make_membership(db_session, organization=org, user=owner_user, role=Role.MEMBER)
    project = await make_project(db_session, organization=org, owner=owner)

    target_user = await make_user(db_session, email=f"matrix-target-{org.id}@x.com")
    await make_membership(db_session, organization=org, user=target_user, role=Role.MEMBER)
    target_member = await make_project_member(db_session, project=project, user=target_user)
    add_user = await make_user(db_session, email=f"matrix-add-{org.id}@x.com")
    await make_membership(db_session, organization=org, user=add_user, role=Role.MEMBER)

    if access == "owner":
        actor_user, actor_membership, actor_org = owner_user, owner, org
    elif access in ("manager", "non_owner"):
        actor_user = await make_user(db_session, email=f"matrix-{access}-{org.id}@x.com")
        actor_membership = await make_membership(
            db_session,
            organization=org,
            user=actor_user,
            role=Role.MANAGER if access == "manager" else Role.MEMBER,
        )
        actor_org = org
    else:
        actor_org = await make_organization(db_session)
        actor_user = await make_user(db_session, email=f"matrix-cross-{actor_org.id}@x.com")
        actor_membership = await make_membership(
            db_session, organization=actor_org, user=actor_user, role=Role.MEMBER
        )
    await db_session.commit()

    actor = await login_as_existing(
        client,
        fake_verifier,
        user=actor_user,
        membership=actor_membership,
        organization=actor_org,
    )
    path = path_template.format(project_id=project.id, member_id=target_member.id)
    resolved_body = (
        {key: value.format(add_user_id=add_user.id) for key, value in body.items()}
        if body is not None
        else None
    )
    headers = {"X-CSRF-Token": actor.csrf_token} if method != "GET" else {}
    response = await client.request(method, path, json=resolved_body, headers=headers)
    assert response.status_code == (success_status if expected_status is None else expected_status)


@pytest.mark.parametrize(
    ("method", "body", "success_status"),
    [
        ("PATCH", {"title": "Renamed"}, 200),
        ("DELETE", None, 204),
    ],
)
@pytest.mark.parametrize(
    ("access", "expected_status"),
    [
        ("manager", None),
        ("assignee", None),
        ("creator", None),
        ("unrelated_member", 403),
        ("cross_org", 404),
    ],
)
async def test_task_write_routes_enforce_ownership_split(
    client: AsyncClient,
    fake_verifier,
    db_session,
    method: str,
    body: dict[str, str] | None,
    success_status: int,
    access: str,
    expected_status: int | None,
) -> None:
    """RBAC.md §3 'Task edit': MANAGER+ or the task's own assignee or
    creator — the same rule governs delete (ROADMAP.md Stage 3 decision).
    Covers every case the route/service split exists to distinguish, plus
    the two escape hatches (assignee vs creator) being independent of each
    other."""
    org = await make_organization(db_session)
    creator_user = await make_user(db_session, email=f"task-creator-{org.id}@x.com")
    creator = await make_membership(
        db_session, organization=org, user=creator_user, role=Role.MEMBER
    )
    assignee_user = await make_user(db_session, email=f"task-assignee-{org.id}@x.com")
    assignee = await make_membership(
        db_session, organization=org, user=assignee_user, role=Role.MEMBER
    )
    task = await make_task(db_session, organization=org, created_by=creator, assignee=assignee)

    if access == "creator":
        actor_user, actor_membership, actor_org = creator_user, creator, org
    elif access == "assignee":
        actor_user, actor_membership, actor_org = assignee_user, assignee, org
    elif access in ("manager", "unrelated_member"):
        actor_user = await make_user(db_session, email=f"task-{access}-{org.id}@x.com")
        actor_membership = await make_membership(
            db_session,
            organization=org,
            user=actor_user,
            role=Role.MANAGER if access == "manager" else Role.MEMBER,
        )
        actor_org = org
    else:
        actor_org = await make_organization(db_session)
        actor_user = await make_user(db_session, email=f"task-cross-{actor_org.id}@x.com")
        actor_membership = await make_membership(
            db_session, organization=actor_org, user=actor_user, role=Role.MEMBER
        )
    await db_session.commit()

    actor = await login_as_existing(
        client,
        fake_verifier,
        user=actor_user,
        membership=actor_membership,
        organization=actor_org,
    )
    headers = {"X-CSRF-Token": actor.csrf_token}
    response = await client.request(method, f"/api/v1/tasks/{task.id}", json=body, headers=headers)
    assert response.status_code == (success_status if expected_status is None else expected_status)


@pytest.mark.parametrize(
    ("access", "expected_status"),
    [("manager", 200), ("member", 200), ("outsider", 403), ("cross_org", 404)],
)
async def test_project_milestones_list_enforces_project_visibility(
    client: AsyncClient, fake_verifier, db_session, access: str, expected_status: int
) -> None:
    """Same shape as 'Project detail' (RBAC.md §3): route is PROJECT_READ
    (MEMBER-tier), service is ensure_project_visible (MANAGER+ or project
    membership)."""
    org = await make_organization(db_session)
    owner_user = await make_user(db_session, email=f"milestone-owner-{org.id}@x.com")
    owner = await make_membership(db_session, organization=org, user=owner_user, role=Role.OWNER)
    project = await make_project(db_session, organization=org, owner=owner)

    if access == "manager":
        actor_user = await make_user(db_session, email=f"milestone-manager-{org.id}@x.com")
        actor_membership = await make_membership(
            db_session, organization=org, user=actor_user, role=Role.MANAGER
        )
        actor_org = org
    elif access == "member":
        actor_user = await make_user(db_session, email=f"milestone-member-{org.id}@x.com")
        actor_membership = await make_membership(
            db_session, organization=org, user=actor_user, role=Role.MEMBER
        )
        await make_project_member(db_session, project=project, user=actor_user)
        actor_org = org
    elif access == "outsider":
        actor_user = await make_user(db_session, email=f"milestone-outsider-{org.id}@x.com")
        actor_membership = await make_membership(
            db_session, organization=org, user=actor_user, role=Role.MEMBER
        )
        actor_org = org
    else:
        actor_org = await make_organization(db_session)
        actor_user = await make_user(db_session, email=f"milestone-cross-{actor_org.id}@x.com")
        actor_membership = await make_membership(
            db_session, organization=actor_org, user=actor_user, role=Role.MEMBER
        )
    await db_session.commit()

    await login_as_existing(
        client,
        fake_verifier,
        user=actor_user,
        membership=actor_membership,
        organization=actor_org,
    )
    response = await client.get(f"/api/v1/projects/{project.id}/milestones")
    assert response.status_code == expected_status


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
        # Every row using this placeholder (PATCH/DELETE project, POST
        # milestone) is MANAGER+-only with no ownership escape hatch, so
        # who owns the test project doesn't affect the assertion below.
        project = await make_project(db_session, organization=actor.organization, owner=target)
        await db_session.commit()
        resolved_path = resolved_path.replace("{project_id}", str(project.id))
    if "{task_id}" in resolved_path:
        # TASK_READ has no per-resource restriction (ROADMAP.md Stage 3
        # decision) — a real task proves every role can genuinely read it,
        # not just that a phantom lookup happens not to 404 into a 403.
        task = await make_task(db_session, organization=actor.organization, created_by=target)
        await db_session.commit()
        resolved_path = resolved_path.replace("{task_id}", str(task.id))
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

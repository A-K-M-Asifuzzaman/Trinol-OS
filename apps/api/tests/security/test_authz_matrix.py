from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.factories import make_membership, make_user
from tests.helpers import login_as
from trinol.core.authz.permissions import Role

# RBAC.md §6: for every route x every role x own resource, assert the
# expected status. Team routes only for now (they're the first routes this
# repo has that need role-differentiated behavior beyond a flat public/
# authenticated split) — Stage 11 adds the meta-assertion that fails when a
# new route has no row here.

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

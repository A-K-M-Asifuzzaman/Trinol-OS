from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.factories import make_membership, make_organization, make_project, make_user
from tests.helpers import login_as, login_as_existing
from trinol.core.authz.permissions import Role

# RBAC.md §3 / ROADMAP.md Phase 2 decision 6: project member management is
# gated at the route by PROJECT_MEMBER_WRITE (MEMBER-tier — everyone
# reaches the service) and at the service by MANAGER+ OR
# project.owner_id == actor.user_id. The four cases below are exactly the
# ones that split exists to distinguish.

pytestmark = pytest.mark.usefixtures("db_session")


@pytest.mark.parametrize("role", [Role.MANAGER, Role.ADMIN, Role.OWNER])
async def test_manager_and_up_can_add_a_member_to_any_project(
    client: AsyncClient, fake_verifier, db_session, role: Role
) -> None:
    owner_actor = await login_as(client, fake_verifier, db_session, role=Role.OWNER)
    project = await make_project(
        db_session, organization=owner_actor.organization, owner=owner_actor.membership
    )
    target_user = await make_user(db_session, email=f"target-{owner_actor.organization.id}@x.com")
    await make_membership(
        db_session, organization=owner_actor.organization, user=target_user, role=Role.MEMBER
    )
    await db_session.commit()

    actor_user = await make_user(
        db_session, email=f"actor-{owner_actor.organization.id}-{role}@x.com"
    )
    actor_membership = await make_membership(
        db_session, organization=owner_actor.organization, user=actor_user, role=role
    )
    await db_session.commit()
    actor = await login_as_existing(
        client,
        fake_verifier,
        user=actor_user,
        membership=actor_membership,
        organization=owner_actor.organization,
    )

    response = await client.post(
        f"/api/v1/projects/{project.id}/members",
        json={"user_id": str(target_user.id)},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == 201
    assert response.json()["role_on_project"] == "CONTRIBUTOR"


async def test_member_who_owns_the_project_can_add_a_member(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    """The case the route/service split exists to allow: a MEMBER-role
    project owner reaches the service (PROJECT_MEMBER_WRITE is MEMBER-tier)
    and is authorized there via project.owner_id == actor.user_id, not role."""
    org = await make_organization(db_session)
    owner_user = await make_user(db_session, email=f"owner-{org.id}@x.com")
    owner_membership = await make_membership(
        db_session, organization=org, user=owner_user, role=Role.MEMBER
    )
    # make_project already adds the owner as a project_members row (LEAD).
    project = await make_project(db_session, organization=org, owner=owner_membership)

    target_user = await make_user(db_session, email=f"target-{org.id}@x.com")
    await make_membership(db_session, organization=org, user=target_user, role=Role.MEMBER)
    await db_session.commit()

    actor = await login_as_existing(
        client, fake_verifier, user=owner_user, membership=owner_membership, organization=org
    )
    response = await client.post(
        f"/api/v1/projects/{project.id}/members",
        json={"user_id": str(target_user.id)},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == 201


async def test_member_who_does_not_own_the_project_gets_403(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    org = await make_organization(db_session)
    owner_user = await make_user(db_session, email=f"owner2-{org.id}@x.com")
    owner_membership = await make_membership(
        db_session, organization=org, user=owner_user, role=Role.MEMBER
    )
    project = await make_project(db_session, organization=org, owner=owner_membership)

    non_owner_user = await make_user(db_session, email=f"nonowner-{org.id}@x.com")
    non_owner_membership = await make_membership(
        db_session, organization=org, user=non_owner_user, role=Role.MEMBER
    )
    target_user = await make_user(db_session, email=f"target2-{org.id}@x.com")
    await make_membership(db_session, organization=org, user=target_user, role=Role.MEMBER)
    await db_session.commit()

    actor = await login_as_existing(
        client,
        fake_verifier,
        user=non_owner_user,
        membership=non_owner_membership,
        organization=org,
    )
    response = await client.post(
        f"/api/v1/projects/{project.id}/members",
        json={"user_id": str(target_user.id)},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == 403


async def test_add_member_cross_org_project_is_404(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    other_org = await make_organization(db_session)
    other_owner_user = await make_user(db_session, email=f"owner3-{other_org.id}@x.com")
    other_owner_membership = await make_membership(
        db_session, organization=other_org, user=other_owner_user, role=Role.OWNER
    )
    other_project = await make_project(
        db_session, organization=other_org, owner=other_owner_membership
    )
    await db_session.commit()

    actor = await login_as(client, fake_verifier, db_session, role=Role.ADMIN)
    target_user = await make_user(db_session, email=f"target3-{actor.organization.id}@x.com")
    await make_membership(
        db_session, organization=actor.organization, user=target_user, role=Role.MEMBER
    )
    await db_session.commit()

    response = await client.post(
        f"/api/v1/projects/{other_project.id}/members",
        json={"user_id": str(target_user.id)},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == 404


async def test_add_duplicate_member_conflicts(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.OWNER)
    project = await make_project(
        db_session, organization=actor.organization, owner=actor.membership
    )
    target_user = await make_user(db_session, email=f"target4-{actor.organization.id}@x.com")
    await make_membership(
        db_session, organization=actor.organization, user=target_user, role=Role.MEMBER
    )
    await db_session.commit()

    body = {"user_id": str(target_user.id)}
    first = await client.post(
        f"/api/v1/projects/{project.id}/members",
        json=body,
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert first.status_code == 201
    second = await client.post(
        f"/api/v1/projects/{project.id}/members",
        json=body,
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert second.status_code == 409


async def test_add_member_not_in_organization_is_rejected(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.OWNER)
    project = await make_project(
        db_session, organization=actor.organization, owner=actor.membership
    )
    other_org = await make_organization(db_session)
    outsider = await make_user(db_session, email=f"outsider2-{other_org.id}@x.com")
    await make_membership(db_session, organization=other_org, user=outsider, role=Role.MEMBER)
    await db_session.commit()

    response = await client.post(
        f"/api/v1/projects/{project.id}/members",
        json={"user_id": str(outsider.id)},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == 400


async def test_update_member_role_on_project(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.OWNER)
    project = await make_project(
        db_session, organization=actor.organization, owner=actor.membership
    )
    target_user = await make_user(db_session, email=f"target5-{actor.organization.id}@x.com")
    await make_membership(
        db_session, organization=actor.organization, user=target_user, role=Role.MEMBER
    )
    await db_session.commit()

    add_response = await client.post(
        f"/api/v1/projects/{project.id}/members",
        json={"user_id": str(target_user.id)},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    member_id = add_response.json()["id"]

    response = await client.patch(
        f"/api/v1/projects/{project.id}/members/{member_id}",
        json={"role_on_project": "LEAD"},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == 200
    assert response.json()["role_on_project"] == "LEAD"


async def test_remove_member(client: AsyncClient, fake_verifier, db_session) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.OWNER)
    project = await make_project(
        db_session, organization=actor.organization, owner=actor.membership
    )
    target_user = await make_user(db_session, email=f"target6-{actor.organization.id}@x.com")
    await make_membership(
        db_session, organization=actor.organization, user=target_user, role=Role.MEMBER
    )
    await db_session.commit()

    add_response = await client.post(
        f"/api/v1/projects/{project.id}/members",
        json={"user_id": str(target_user.id)},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    member_id = add_response.json()["id"]

    response = await client.delete(
        f"/api/v1/projects/{project.id}/members/{member_id}",
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == 204

    list_response = await client.get(f"/api/v1/projects/{project.id}/members")
    member_ids = {m["id"] for m in list_response.json()["items"]}
    assert member_id not in member_ids


async def test_cannot_remove_the_project_owner(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.OWNER)
    project = await make_project(
        db_session, organization=actor.organization, owner=actor.membership
    )
    await db_session.commit()

    members_response = await client.get(f"/api/v1/projects/{project.id}/members")
    owner_member_id = members_response.json()["items"][0]["id"]

    response = await client.delete(
        f"/api/v1/projects/{project.id}/members/{owner_member_id}",
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == 409

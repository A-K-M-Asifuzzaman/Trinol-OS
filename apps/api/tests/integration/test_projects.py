from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.factories import (
    make_membership,
    make_organization,
    make_project,
    make_project_member,
    make_user,
)
from tests.helpers import login_as, login_as_existing
from trinol.core.authz.permissions import Role

pytestmark = pytest.mark.usefixtures("db_session")


@pytest.mark.parametrize("role", [Role.MANAGER, Role.ADMIN, Role.OWNER])
async def test_manager_and_up_can_create_project(
    client: AsyncClient, fake_verifier, db_session, role: Role
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=role)
    response = await client.post(
        "/api/v1/projects",
        json={"project_code": "WEB", "name": "Website Redesign"},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["project_code"] == "WEB"
    assert body["owner_id"] == str(actor.membership.user_id)


async def test_member_cannot_create_project(client: AsyncClient, fake_verifier, db_session) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.MEMBER)
    response = await client.post(
        "/api/v1/projects",
        json={"project_code": "WEB", "name": "Website Redesign"},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == 403


async def test_create_project_auto_adds_owner_as_lead_member(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.OWNER)
    create_response = await client.post(
        "/api/v1/projects",
        json={"project_code": "WEB", "name": "Website Redesign"},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    project_id = create_response.json()["id"]

    members_response = await client.get(f"/api/v1/projects/{project_id}/members")
    assert members_response.status_code == 200
    items = members_response.json()["items"]
    assert len(items) == 1
    assert items[0]["user_id"] == str(actor.membership.user_id)
    assert items[0]["role_on_project"] == "LEAD"


async def test_create_project_can_assign_a_different_owner(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.ADMIN)
    other_user = await make_user(db_session, email=f"owner-{actor.organization.id}@x.com")
    other_membership = await make_membership(
        db_session, organization=actor.organization, user=other_user, role=Role.MEMBER
    )
    await db_session.commit()

    response = await client.post(
        "/api/v1/projects",
        json={"project_code": "WEB", "name": "Website Redesign", "owner_id": str(other_user.id)},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == 201
    assert response.json()["owner_id"] == str(other_membership.user_id)


async def test_create_project_rejects_owner_not_in_organization(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.ADMIN)
    other_org = await make_organization(db_session)
    outsider = await make_user(db_session, email=f"outsider-{other_org.id}@x.com")
    await make_membership(db_session, organization=other_org, user=outsider, role=Role.MEMBER)
    await db_session.commit()

    response = await client.post(
        "/api/v1/projects",
        json={"project_code": "WEB", "name": "Website Redesign", "owner_id": str(outsider.id)},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == 400


async def test_duplicate_project_code_conflicts(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.OWNER)
    body = {"project_code": "WEB", "name": "Website Redesign"}
    first = await client.post(
        "/api/v1/projects", json=body, headers={"X-CSRF-Token": actor.csrf_token}
    )
    assert first.status_code == 201
    second = await client.post(
        "/api/v1/projects", json=body, headers={"X-CSRF-Token": actor.csrf_token}
    )
    assert second.status_code == 409


async def test_deadline_before_start_date_is_rejected(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.OWNER)
    response = await client.post(
        "/api/v1/projects",
        json={
            "project_code": "WEB",
            "name": "Website Redesign",
            "start_date": "2026-06-01",
            "deadline": "2026-01-01",
        },
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == 422


async def test_list_projects_excludes_archived(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    """ADR-0011: the list endpoint excludes archived rows."""
    actor = await login_as(client, fake_verifier, db_session, role=Role.OWNER)
    create_response = await client.post(
        "/api/v1/projects",
        json={"project_code": "WEB", "name": "Website Redesign"},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    project_id = create_response.json()["id"]

    delete_response = await client.delete(
        f"/api/v1/projects/{project_id}", headers={"X-CSRF-Token": actor.csrf_token}
    )
    assert delete_response.status_code == 200
    assert delete_response.json()["archived_at"] is not None

    list_response = await client.get("/api/v1/projects")
    assert list_response.status_code == 200
    assert list_response.json()["items"] == []

    # Still reachable directly, just not listed.
    get_response = await client.get(f"/api/v1/projects/{project_id}")
    assert get_response.status_code == 200


async def test_member_only_sees_projects_they_belong_to(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    owner_actor = await login_as(client, fake_verifier, db_session, role=Role.OWNER)
    owner_membership = owner_actor.membership

    visible = await make_project(
        db_session, organization=owner_actor.organization, owner=owner_membership, name="Visible"
    )
    hidden = await make_project(
        db_session, organization=owner_actor.organization, owner=owner_membership, name="Hidden"
    )
    member_user = await make_user(db_session, email=f"member-{owner_actor.organization.id}@x.com")
    member_membership = await make_membership(
        db_session, organization=owner_actor.organization, user=member_user, role=Role.MEMBER
    )
    await make_project_member(db_session, project=visible, user=member_user)
    await db_session.commit()

    await login_as_existing(
        client,
        fake_verifier,
        user=member_user,
        membership=member_membership,
        organization=owner_actor.organization,
    )

    response = await client.get("/api/v1/projects")
    assert response.status_code == 200
    names = {item["name"] for item in response.json()["items"]}
    assert names == {"Visible"}
    assert hidden.id  # sanity: hidden project really exists, just not listed


async def test_get_project_in_another_org_is_404(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    other_org = await make_organization(db_session)
    other_owner_user = await make_user(db_session, email=f"owner-{other_org.id}@x.com")
    other_owner_membership = await make_membership(
        db_session, organization=other_org, user=other_owner_user, role=Role.OWNER
    )
    other_project = await make_project(
        db_session, organization=other_org, owner=other_owner_membership
    )
    await db_session.commit()

    await login_as(client, fake_verifier, db_session, role=Role.ADMIN)
    response = await client.get(f"/api/v1/projects/{other_project.id}")
    assert response.status_code == 404


async def test_member_not_on_project_gets_403_on_detail(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    owner_actor = await login_as(client, fake_verifier, db_session, role=Role.OWNER)
    project = await make_project(
        db_session, organization=owner_actor.organization, owner=owner_actor.membership
    )
    outsider_user = await make_user(
        db_session, email=f"outsider-{owner_actor.organization.id}@x.com"
    )
    outsider_membership = await make_membership(
        db_session, organization=owner_actor.organization, user=outsider_user, role=Role.MEMBER
    )
    await db_session.commit()

    await login_as_existing(
        client,
        fake_verifier,
        user=outsider_user,
        membership=outsider_membership,
        organization=owner_actor.organization,
    )
    response = await client.get(f"/api/v1/projects/{project.id}")
    assert response.status_code == 403


async def test_manager_can_edit_project_fields(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.MANAGER)
    create_response = await client.post(
        "/api/v1/projects",
        json={"project_code": "WEB", "name": "Website Redesign"},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    project_id = create_response.json()["id"]

    response = await client.patch(
        f"/api/v1/projects/{project_id}",
        json={"name": "Renamed", "status": "ACTIVE"},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == 200
    assert response.json()["name"] == "Renamed"
    assert response.json()["status"] == "ACTIVE"
    # Partial update: untouched fields keep their original value.
    assert response.json()["project_code"] == "WEB"


async def test_member_cannot_edit_project(client: AsyncClient, fake_verifier, db_session) -> None:
    owner_actor = await login_as(client, fake_verifier, db_session, role=Role.OWNER)
    project = await make_project(
        db_session, organization=owner_actor.organization, owner=owner_actor.membership
    )
    await db_session.commit()

    outsider_user = await make_user(
        db_session, email=f"member2-{owner_actor.organization.id}@x.com"
    )
    outsider_membership = await make_membership(
        db_session, organization=owner_actor.organization, user=outsider_user, role=Role.MEMBER
    )
    await db_session.commit()

    actor = await login_as_existing(
        client,
        fake_verifier,
        user=outsider_user,
        membership=outsider_membership,
        organization=owner_actor.organization,
    )
    response = await client.patch(
        f"/api/v1/projects/{project.id}",
        json={"name": "Hijacked"},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == 403


@pytest.mark.parametrize(
    ("role", "expected_status"),
    [(Role.MANAGER, 403), (Role.ADMIN, 200), (Role.OWNER, 200)],
)
async def test_delete_project_requires_admin_or_owner(
    client: AsyncClient, fake_verifier, db_session, role: Role, expected_status: int
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=role)
    project = await make_project(
        db_session, organization=actor.organization, owner=actor.membership
    )
    await db_session.commit()

    response = await client.delete(
        f"/api/v1/projects/{project.id}", headers={"X-CSRF-Token": actor.csrf_token}
    )
    assert response.status_code == expected_status

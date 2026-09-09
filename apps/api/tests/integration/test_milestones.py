from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.factories import make_membership, make_organization, make_project, make_user
from tests.helpers import login_as, login_as_existing
from trinol.core.authz.permissions import Role

pytestmark = pytest.mark.usefixtures("db_session")


@pytest.mark.parametrize("role", [Role.MANAGER, Role.ADMIN, Role.OWNER])
async def test_manager_and_up_can_create_milestone(
    client: AsyncClient, fake_verifier, db_session, role: Role
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=role)
    project = await make_project(
        db_session, organization=actor.organization, owner=actor.membership
    )
    await db_session.commit()

    response = await client.post(
        f"/api/v1/projects/{project.id}/milestones",
        json={"name": "Beta launch"},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == 201
    assert response.json()["name"] == "Beta launch"


async def test_member_owner_cannot_create_milestone(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    """Milestones follow 'Create/edit projects' (MANAGER+), not decision
    6's project-member-management ownership exception — RBAC.md §3 only
    documents that exception for project_members specifically."""
    org = await make_organization(db_session)
    owner_user = await make_user(db_session, email=f"milestone-member-owner-{org.id}@x.com")
    owner_membership = await make_membership(
        db_session, organization=org, user=owner_user, role=Role.MEMBER
    )
    project = await make_project(db_session, organization=org, owner=owner_membership)
    await db_session.commit()

    actor = await login_as_existing(
        client, fake_verifier, user=owner_user, membership=owner_membership, organization=org
    )
    response = await client.post(
        f"/api/v1/projects/{project.id}/milestones",
        json={"name": "Beta launch"},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == 403


async def test_create_milestone_in_another_org_project_is_404(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    other_org = await make_organization(db_session)
    other_owner_user = await make_user(db_session, email=f"other-owner-{other_org.id}@x.com")
    other_owner = await make_membership(
        db_session, organization=other_org, user=other_owner_user, role=Role.OWNER
    )
    other_project = await make_project(db_session, organization=other_org, owner=other_owner)
    await db_session.commit()

    actor = await login_as(client, fake_verifier, db_session, role=Role.ADMIN)
    response = await client.post(
        f"/api/v1/projects/{other_project.id}/milestones",
        json={"name": "Beta launch"},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == 404


async def test_list_milestones_orders_by_position(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.OWNER)
    project = await make_project(
        db_session, organization=actor.organization, owner=actor.membership
    )
    await db_session.commit()

    for name, position in [("Third", 2), ("First", 0), ("Second", 1)]:
        await client.post(
            f"/api/v1/projects/{project.id}/milestones",
            json={"name": name, "position": position},
            headers={"X-CSRF-Token": actor.csrf_token},
        )

    response = await client.get(f"/api/v1/projects/{project.id}/milestones")
    assert response.status_code == 200
    names = [item["name"] for item in response.json()["items"]]
    assert names == ["First", "Second", "Third"]

from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.factories import make_membership, make_organization, make_user
from tests.helpers import login_as
from trinol.core.authz.permissions import Role
from trinol.modules.work.models import ProjectHealth, ProjectStatus
from trinol.modules.work.services.project_service import create_project

pytestmark = pytest.mark.usefixtures("db_session")


async def test_activity_feed_returns_items_and_total(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.OWNER)
    await client.post(
        "/api/v1/projects",
        json={"project_code": "WEB", "name": "Website Redesign"},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    await client.post(
        "/api/v1/tasks", json={"title": "Task"}, headers={"X-CSRF-Token": actor.csrf_token}
    )

    response = await client.get("/api/v1/activity")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert {item["event"] for item in body["items"]} == {"task.created", "project.created"}


async def test_activity_feed_excludes_audit_only_events(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    """project_member.added/removed are audit=true (RBAC.md §3 guard 6) and
    must not leak into the ordinary feed, even though they happen inside the
    same org as visible feed content."""
    actor = await login_as(client, fake_verifier, db_session, role=Role.OWNER)
    project_response = await client.post(
        "/api/v1/projects",
        json={"project_code": "WEB", "name": "Website Redesign"},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    project_id = project_response.json()["id"]

    target_user = await make_user(db_session, email=f"member-{project_id}@x.com")
    await make_membership(
        db_session, organization=actor.organization, user=target_user, role=Role.MEMBER
    )
    await db_session.commit()

    add_response = await client.post(
        f"/api/v1/projects/{project_id}/members",
        json={"user_id": str(target_user.id)},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert add_response.status_code == 201
    member_id = add_response.json()["id"]

    remove_response = await client.delete(
        f"/api/v1/projects/{project_id}/members/{member_id}",
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert remove_response.status_code == 204

    response = await client.get("/api/v1/activity")
    body = response.json()
    assert body["total"] == 1
    events = [item["event"] for item in body["items"]]
    assert events == ["project.created"]


async def test_activity_feed_is_org_scoped(client: AsyncClient, fake_verifier, db_session) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.OWNER)
    await client.post(
        "/api/v1/projects",
        json={"project_code": "WEB", "name": "Website Redesign"},
        headers={"X-CSRF-Token": actor.csrf_token},
    )

    other_org = await make_organization(db_session)
    other_user = await make_user(db_session, email=f"other-{other_org.id}@x.com")
    other_actor = await make_membership(
        db_session, organization=other_org, user=other_user, role=Role.OWNER
    )
    await db_session.commit()
    await create_project(
        db_session,
        organization_id=other_org.id,
        actor=other_actor,
        project_code="OTHERORG",
        name="Other Org Project",
        description=None,
        status=ProjectStatus.PLANNING,
        health=ProjectHealth.ON_TRACK,
        owner_id=None,
        start_date=None,
        deadline=None,
        budget=None,
        currency="USD",
        repository_url=None,
        production_url=None,
        staging_url=None,
    )
    await db_session.commit()

    response = await client.get("/api/v1/activity")
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["event"] == "project.created"

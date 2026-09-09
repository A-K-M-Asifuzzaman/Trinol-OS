from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.factories import (
    make_membership,
    make_milestone,
    make_organization,
    make_project,
    make_task,
    make_user,
)
from tests.helpers import login_as, login_as_existing
from trinol.core.authz.permissions import Role
from trinol.platform.activity import list_audit

pytestmark = pytest.mark.usefixtures("db_session")


async def test_any_role_can_create_a_task(client: AsyncClient, fake_verifier, db_session) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.MEMBER)
    response = await client.post(
        "/api/v1/tasks",
        json={"title": "Write the docs"},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["title"] == "Write the docs"
    assert body["created_by"] == str(actor.membership.user_id)
    assert body["status"] == "TODO"
    assert body["completed_at"] is None


async def test_create_task_can_assign_to_another_member(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.MEMBER)
    assignee_user = await make_user(db_session, email=f"assignee-{actor.organization.id}@x.com")
    assignee_membership = await make_membership(
        db_session, organization=actor.organization, user=assignee_user, role=Role.MEMBER
    )
    await db_session.commit()

    response = await client.post(
        "/api/v1/tasks",
        json={"title": "Review PR", "assignee_id": str(assignee_user.id)},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == 201
    assert response.json()["assignee_id"] == str(assignee_membership.user_id)


async def test_create_task_rejects_assignee_outside_organization(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.MEMBER)
    other_org = await make_organization(db_session)
    outsider = await make_user(db_session, email=f"outsider-{other_org.id}@x.com")
    await make_membership(db_session, organization=other_org, user=outsider, role=Role.MEMBER)
    await db_session.commit()

    response = await client.post(
        "/api/v1/tasks",
        json={"title": "Task", "assignee_id": str(outsider.id)},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == 400


async def test_create_task_with_project_and_milestone(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.OWNER)
    project = await make_project(
        db_session, organization=actor.organization, owner=actor.membership
    )
    milestone = await make_milestone(db_session, project=project)
    await db_session.commit()

    response = await client.post(
        "/api/v1/tasks",
        json={
            "title": "Ship it",
            "project_id": str(project.id),
            "milestone_id": str(milestone.id),
        },
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == 201
    assert response.json()["milestone_id"] == str(milestone.id)


async def test_create_task_rejects_milestone_from_a_different_project(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.OWNER)
    project_a = await make_project(
        db_session, organization=actor.organization, owner=actor.membership, project_code="A"
    )
    project_b = await make_project(
        db_session, organization=actor.organization, owner=actor.membership, project_code="B"
    )
    milestone_b = await make_milestone(db_session, project=project_b)
    await db_session.commit()

    response = await client.post(
        "/api/v1/tasks",
        json={
            "title": "Mismatched",
            "project_id": str(project_a.id),
            "milestone_id": str(milestone_b.id),
        },
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == 400


async def test_create_task_rejects_milestone_without_project(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.OWNER)
    project = await make_project(
        db_session, organization=actor.organization, owner=actor.membership
    )
    milestone = await make_milestone(db_session, project=project)
    await db_session.commit()

    response = await client.post(
        "/api/v1/tasks",
        json={"title": "Orphaned milestone", "milestone_id": str(milestone.id)},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == 400


async def test_setting_status_done_sets_completed_at(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.MEMBER)
    create_response = await client.post(
        "/api/v1/tasks",
        json={"title": "Finish me"},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    task_id = create_response.json()["id"]

    response = await client.patch(
        f"/api/v1/tasks/{task_id}",
        json={"status": "DONE"},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == 200
    assert response.json()["completed_at"] is not None

    # Moving back off DONE clears it again.
    response = await client.patch(
        f"/api/v1/tasks/{task_id}",
        json={"status": "IN_PROGRESS"},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == 200
    assert response.json()["completed_at"] is None


async def test_assignee_can_edit_their_own_task(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    org = await make_organization(db_session)
    creator_user = await make_user(db_session, email=f"creator-{org.id}@x.com")
    creator = await make_membership(
        db_session, organization=org, user=creator_user, role=Role.MEMBER
    )
    assignee_user = await make_user(db_session, email=f"assignee2-{org.id}@x.com")
    assignee = await make_membership(
        db_session, organization=org, user=assignee_user, role=Role.MEMBER
    )
    task = await make_task(db_session, organization=org, created_by=creator, assignee=assignee)
    await db_session.commit()

    actor = await login_as_existing(
        client, fake_verifier, user=assignee_user, membership=assignee, organization=org
    )
    response = await client.patch(
        f"/api/v1/tasks/{task.id}",
        json={"priority": "HIGH"},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == 200
    assert response.json()["priority"] == "HIGH"


async def test_unrelated_member_cannot_edit_task(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    org = await make_organization(db_session)
    creator_user = await make_user(db_session, email=f"creator2-{org.id}@x.com")
    creator = await make_membership(
        db_session, organization=org, user=creator_user, role=Role.MEMBER
    )
    task = await make_task(db_session, organization=org, created_by=creator)

    outsider_user = await make_user(db_session, email=f"outsider2-{org.id}@x.com")
    outsider = await make_membership(
        db_session, organization=org, user=outsider_user, role=Role.MEMBER
    )
    await db_session.commit()

    actor = await login_as_existing(
        client, fake_verifier, user=outsider_user, membership=outsider, organization=org
    )
    response = await client.patch(
        f"/api/v1/tasks/{task.id}",
        json={"title": "Hijacked"},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == 403


async def test_get_task_in_another_org_is_404(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    other_org = await make_organization(db_session)
    other_user = await make_user(db_session, email=f"other-{other_org.id}@x.com")
    other_membership = await make_membership(
        db_session, organization=other_org, user=other_user, role=Role.MEMBER
    )
    other_task = await make_task(db_session, organization=other_org, created_by=other_membership)
    await db_session.commit()

    await login_as(client, fake_verifier, db_session, role=Role.ADMIN)
    response = await client.get(f"/api/v1/tasks/{other_task.id}")
    assert response.status_code == 404


async def test_any_member_can_read_any_task_in_the_org(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    """ROADMAP.md Stage 3 decision: TASK_READ is org-wide, unlike Project
    detail — no per-resource restriction on reading a task."""
    org = await make_organization(db_session)
    creator_user = await make_user(db_session, email=f"creator3-{org.id}@x.com")
    creator = await make_membership(
        db_session, organization=org, user=creator_user, role=Role.MEMBER
    )
    task = await make_task(db_session, organization=org, created_by=creator)

    reader_user = await make_user(db_session, email=f"reader-{org.id}@x.com")
    reader = await make_membership(db_session, organization=org, user=reader_user, role=Role.MEMBER)
    await db_session.commit()

    await login_as_existing(
        client, fake_verifier, user=reader_user, membership=reader, organization=org
    )
    response = await client.get(f"/api/v1/tasks/{task.id}")
    assert response.status_code == 200


async def test_list_tasks_filters_by_assignee(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.OWNER)
    other_user = await make_user(db_session, email=f"other3-{actor.organization.id}@x.com")
    other_membership = await make_membership(
        db_session, organization=actor.organization, user=other_user, role=Role.MEMBER
    )
    await db_session.commit()

    mine = await client.post(
        "/api/v1/tasks",
        json={"title": "Mine", "assignee_id": str(actor.membership.user_id)},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    await client.post(
        "/api/v1/tasks",
        json={"title": "Theirs", "assignee_id": str(other_user.id)},
        headers={"X-CSRF-Token": actor.csrf_token},
    )

    response = await client.get(
        "/api/v1/tasks", params={"assignee_id": str(actor.membership.user_id)}
    )
    assert response.status_code == 200
    items = response.json()["items"]
    assert {item["id"] for item in items} == {mine.json()["id"]}
    assert other_membership.user_id  # sanity: the other membership really exists


async def test_delete_task_removes_it(client: AsyncClient, fake_verifier, db_session) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.MEMBER)
    create_response = await client.post(
        "/api/v1/tasks",
        json={"title": "Delete me"},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    task_id = create_response.json()["id"]

    response = await client.delete(
        f"/api/v1/tasks/{task_id}", headers={"X-CSRF-Token": actor.csrf_token}
    )
    assert response.status_code == 204

    get_response = await client.get(f"/api/v1/tasks/{task_id}")
    assert get_response.status_code == 404


async def test_delete_task_records_an_audit_event(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    """ADR-0011: "Deleting a task... really deletes it. The audit event
    keeps the record of who did it and when" — the row is gone afterward,
    so this is the only place that history survives."""
    actor = await login_as(client, fake_verifier, db_session, role=Role.MEMBER)
    create_response = await client.post(
        "/api/v1/tasks",
        json={"title": "Audit me"},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    task_id = create_response.json()["id"]

    response = await client.delete(
        f"/api/v1/tasks/{task_id}", headers={"X-CSRF-Token": actor.csrf_token}
    )
    assert response.status_code == 204

    audit_rows = await list_audit(db_session, organization_id=actor.organization.id)
    deleted_events = [row for row in audit_rows if row.event == "task.deleted"]
    assert len(deleted_events) == 1
    assert str(deleted_events[0].entity_id) == task_id
    assert deleted_events[0].actor_id == actor.membership.user_id


async def test_patch_can_clear_project_id_to_unproject_a_task(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.OWNER)
    project = await make_project(
        db_session, organization=actor.organization, owner=actor.membership
    )
    await db_session.commit()

    create_response = await client.post(
        "/api/v1/tasks",
        json={"title": "Projected", "project_id": str(project.id)},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    task_id = create_response.json()["id"]
    assert create_response.json()["project_id"] == str(project.id)

    response = await client.patch(
        f"/api/v1/tasks/{task_id}",
        json={"project_id": None},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == 200
    assert response.json()["project_id"] is None


async def test_unrelated_member_cannot_delete_task(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    org = await make_organization(db_session)
    creator_user = await make_user(db_session, email=f"creator4-{org.id}@x.com")
    creator = await make_membership(
        db_session, organization=org, user=creator_user, role=Role.MEMBER
    )
    task = await make_task(db_session, organization=org, created_by=creator)

    outsider_user = await make_user(db_session, email=f"outsider3-{org.id}@x.com")
    outsider = await make_membership(
        db_session, organization=org, user=outsider_user, role=Role.MEMBER
    )
    await db_session.commit()

    actor = await login_as_existing(
        client, fake_verifier, user=outsider_user, membership=outsider, organization=org
    )
    response = await client.delete(
        f"/api/v1/tasks/{task.id}", headers={"X-CSRF-Token": actor.csrf_token}
    )
    assert response.status_code == 403

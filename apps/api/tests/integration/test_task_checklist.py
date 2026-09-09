from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.factories import make_membership, make_organization, make_task, make_user
from tests.helpers import login_as
from trinol.core.authz.permissions import Role
from trinol.platform.activity import list_audit

pytestmark = pytest.mark.usefixtures("db_session")


async def test_create_and_list_checklist_items(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.MEMBER)
    task_response = await client.post(
        "/api/v1/tasks", json={"title": "Task"}, headers={"X-CSRF-Token": actor.csrf_token}
    )
    task_id = task_response.json()["id"]

    create_response = await client.post(
        f"/api/v1/tasks/{task_id}/checklist-items",
        json={"label": "Write tests", "position": 0},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert create_response.status_code == 201
    body = create_response.json()
    assert body["label"] == "Write tests"
    assert body["done"] is False

    list_response = await client.get(f"/api/v1/tasks/{task_id}/checklist-items")
    assert list_response.status_code == 200
    assert [i["label"] for i in list_response.json()["items"]] == ["Write tests"]


async def test_toggle_done(client: AsyncClient, fake_verifier, db_session) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.MEMBER)
    task_response = await client.post(
        "/api/v1/tasks", json={"title": "Task"}, headers={"X-CSRF-Token": actor.csrf_token}
    )
    task_id = task_response.json()["id"]
    create_response = await client.post(
        f"/api/v1/tasks/{task_id}/checklist-items",
        json={"label": "Item"},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    item_id = create_response.json()["id"]

    response = await client.patch(
        f"/api/v1/tasks/{task_id}/checklist-items/{item_id}",
        json={"done": True},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == 200
    assert response.json()["done"] is True
    # Untouched fields keep their value (partial update).
    assert response.json()["label"] == "Item"


async def test_reorder_via_position(client: AsyncClient, fake_verifier, db_session) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.MEMBER)
    task_response = await client.post(
        "/api/v1/tasks", json={"title": "Task"}, headers={"X-CSRF-Token": actor.csrf_token}
    )
    task_id = task_response.json()["id"]
    first = await client.post(
        f"/api/v1/tasks/{task_id}/checklist-items",
        json={"label": "First", "position": 0},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    second = await client.post(
        f"/api/v1/tasks/{task_id}/checklist-items",
        json={"label": "Second", "position": 1},
        headers={"X-CSRF-Token": actor.csrf_token},
    )

    await client.patch(
        f"/api/v1/tasks/{task_id}/checklist-items/{first.json()['id']}",
        json={"position": 5},
        headers={"X-CSRF-Token": actor.csrf_token},
    )

    list_response = await client.get(f"/api/v1/tasks/{task_id}/checklist-items")
    labels = [i["label"] for i in list_response.json()["items"]]
    assert labels == ["Second", "First"]
    assert second.json()["label"] == "Second"


async def test_delete_checklist_item_records_an_audit_event(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    """ADR-0011 names checklist items explicitly alongside tasks and
    comments for the audit-on-delete requirement."""
    actor = await login_as(client, fake_verifier, db_session, role=Role.MEMBER)
    task_response = await client.post(
        "/api/v1/tasks", json={"title": "Task"}, headers={"X-CSRF-Token": actor.csrf_token}
    )
    task_id = task_response.json()["id"]
    create_response = await client.post(
        f"/api/v1/tasks/{task_id}/checklist-items",
        json={"label": "Delete me"},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    item_id = create_response.json()["id"]

    response = await client.delete(
        f"/api/v1/tasks/{task_id}/checklist-items/{item_id}",
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == 204

    audit_rows = await list_audit(db_session, organization_id=actor.organization.id)
    deleted_events = [row for row in audit_rows if row.event == "task_checklist_item.deleted"]
    assert len(deleted_events) == 1
    assert str(deleted_events[0].entity_id) == item_id
    assert deleted_events[0].actor_id == actor.membership.user_id

    list_response = await client.get(f"/api/v1/tasks/{task_id}/checklist-items")
    assert list_response.json()["items"] == []


async def test_checklist_on_task_in_another_org_is_404(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    other_org = await make_organization(db_session)
    other_user = await make_user(db_session, email=f"other-{other_org.id}@x.com")
    other_user_membership = await make_membership(
        db_session, organization=other_org, user=other_user, role=Role.MEMBER
    )
    other_task = await make_task(
        db_session, organization=other_org, created_by=other_user_membership
    )
    await db_session.commit()

    await login_as(client, fake_verifier, db_session, role=Role.ADMIN)
    response = await client.get(f"/api/v1/tasks/{other_task.id}/checklist-items")
    assert response.status_code == 404

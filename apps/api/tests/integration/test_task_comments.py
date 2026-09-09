from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.factories import make_membership, make_organization, make_task, make_user
from tests.helpers import login_as, login_as_existing
from trinol.core.authz.permissions import Role
from trinol.platform.activity import list_audit

pytestmark = pytest.mark.usefixtures("db_session")


async def test_create_and_list_comments(client: AsyncClient, fake_verifier, db_session) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.MEMBER)
    task_response = await client.post(
        "/api/v1/tasks", json={"title": "Task"}, headers={"X-CSRF-Token": actor.csrf_token}
    )
    task_id = task_response.json()["id"]

    create_response = await client.post(
        f"/api/v1/tasks/{task_id}/comments",
        json={"body": "First comment"},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert create_response.status_code == 201
    body = create_response.json()
    assert body["body"] == "First comment"
    assert body["author_id"] == str(actor.membership.user_id)
    assert body["edited_at"] is None

    list_response = await client.get(f"/api/v1/tasks/{task_id}/comments")
    assert list_response.status_code == 200
    assert [c["body"] for c in list_response.json()["items"]] == ["First comment"]


async def test_author_can_edit_own_comment_and_edited_at_is_set(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.MEMBER)
    task_response = await client.post(
        "/api/v1/tasks", json={"title": "Task"}, headers={"X-CSRF-Token": actor.csrf_token}
    )
    task_id = task_response.json()["id"]
    create_response = await client.post(
        f"/api/v1/tasks/{task_id}/comments",
        json={"body": "Original"},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    comment_id = create_response.json()["id"]

    response = await client.patch(
        f"/api/v1/tasks/{task_id}/comments/{comment_id}",
        json={"body": "Edited"},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == 200
    assert response.json()["body"] == "Edited"
    assert response.json()["edited_at"] is not None


async def test_non_author_cannot_edit_comment(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    org = await make_organization(db_session)
    author_user = await make_user(db_session, email=f"author-{org.id}@x.com")
    author = await make_membership(db_session, organization=org, user=author_user, role=Role.MEMBER)
    task = await make_task(db_session, organization=org, created_by=author)
    await db_session.commit()

    author_actor = await login_as_existing(
        client, fake_verifier, user=author_user, membership=author, organization=org
    )
    create_response = await client.post(
        f"/api/v1/tasks/{task.id}/comments",
        json={"body": "Original"},
        headers={"X-CSRF-Token": author_actor.csrf_token},
    )
    comment_id = create_response.json()["id"]

    other_user = await make_user(db_session, email=f"other-{org.id}@x.com")
    other = await make_membership(db_session, organization=org, user=other_user, role=Role.ADMIN)
    await db_session.commit()
    other_actor = await login_as_existing(
        client, fake_verifier, user=other_user, membership=other, organization=org
    )

    response = await client.patch(
        f"/api/v1/tasks/{task.id}/comments/{comment_id}",
        json={"body": "Hijacked"},
        headers={"X-CSRF-Token": other_actor.csrf_token},
    )
    assert response.status_code == 403


async def test_admin_can_delete_others_comment_and_it_is_audited(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    org = await make_organization(db_session)
    author_user = await make_user(db_session, email=f"author2-{org.id}@x.com")
    author = await make_membership(db_session, organization=org, user=author_user, role=Role.MEMBER)
    task = await make_task(db_session, organization=org, created_by=author)
    await db_session.commit()

    author_actor = await login_as_existing(
        client, fake_verifier, user=author_user, membership=author, organization=org
    )
    create_response = await client.post(
        f"/api/v1/tasks/{task.id}/comments",
        json={"body": "Delete me"},
        headers={"X-CSRF-Token": author_actor.csrf_token},
    )
    comment_id = create_response.json()["id"]

    admin_user = await make_user(db_session, email=f"admin-{org.id}@x.com")
    admin = await make_membership(db_session, organization=org, user=admin_user, role=Role.ADMIN)
    await db_session.commit()
    admin_actor = await login_as_existing(
        client, fake_verifier, user=admin_user, membership=admin, organization=org
    )

    response = await client.delete(
        f"/api/v1/tasks/{task.id}/comments/{comment_id}",
        headers={"X-CSRF-Token": admin_actor.csrf_token},
    )
    assert response.status_code == 204

    audit_rows = await list_audit(db_session, organization_id=org.id)
    deleted_events = [row for row in audit_rows if row.event == "task_comment.deleted"]
    assert len(deleted_events) == 1
    assert str(deleted_events[0].entity_id) == comment_id
    assert deleted_events[0].actor_id == admin_user.id


async def test_comment_on_task_in_another_org_is_404(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    other_org = await make_organization(db_session)
    other_user = await make_user(db_session, email=f"other2-{other_org.id}@x.com")
    other_membership = await make_membership(
        db_session, organization=other_org, user=other_user, role=Role.MEMBER
    )
    other_task = await make_task(db_session, organization=other_org, created_by=other_membership)
    await db_session.commit()

    await login_as(client, fake_verifier, db_session, role=Role.ADMIN)
    response = await client.get(f"/api/v1/tasks/{other_task.id}/comments")
    assert response.status_code == 404

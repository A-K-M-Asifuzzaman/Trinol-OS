from __future__ import annotations

from decimal import Decimal

import pytest
from httpx import AsyncClient

from tests.factories import make_membership, make_project, make_task, make_user
from tests.helpers import login_as, login_as_existing
from trinol.core.authz.permissions import Role
from trinol.modules.work.models import TaskStatus

pytestmark = pytest.mark.usefixtures("db_session")


async def test_board_groups_tasks_by_status(client: AsyncClient, fake_verifier, db_session) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.OWNER)
    project = await make_project(
        db_session, organization=actor.organization, owner=actor.membership
    )
    await make_task(
        db_session,
        organization=actor.organization,
        created_by=actor.membership,
        project=project,
        title="Todo task",
    )
    await make_task(
        db_session,
        organization=actor.organization,
        created_by=actor.membership,
        project=project,
        title="Done task",
        status=TaskStatus.DONE,
    )
    await db_session.commit()

    response = await client.get(f"/api/v1/projects/{project.id}/board")
    assert response.status_code == 200
    body = response.json()
    columns_by_status = {column["status"]: column["tasks"] for column in body["columns"]}
    assert [t["title"] for t in columns_by_status["TODO"]] == ["Todo task"]
    assert [t["title"] for t in columns_by_status["DONE"]] == ["Done task"]
    assert columns_by_status["IN_PROGRESS"] == []
    assert body["total"] == 2
    assert body["truncated"] is False


async def test_board_orders_within_a_column_by_board_position(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.OWNER)
    project = await make_project(
        db_session, organization=actor.organization, owner=actor.membership
    )
    await make_task(
        db_session,
        organization=actor.organization,
        created_by=actor.membership,
        project=project,
        title="Second",
        board_position=Decimal("2"),
    )
    await make_task(
        db_session,
        organization=actor.organization,
        created_by=actor.membership,
        project=project,
        title="First",
        board_position=Decimal("1"),
    )
    await db_session.commit()

    response = await client.get(f"/api/v1/projects/{project.id}/board")
    todo_tasks = next(c for c in response.json()["columns"] if c["status"] == "TODO")["tasks"]
    assert [t["title"] for t in todo_tasks] == ["First", "Second"]


async def test_board_caps_at_500_tasks_and_reports_truncation(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.OWNER)
    project = await make_project(
        db_session, organization=actor.organization, owner=actor.membership
    )
    for i in range(501):
        await make_task(
            db_session,
            organization=actor.organization,
            created_by=actor.membership,
            project=project,
            title=f"Task {i}",
            board_position=Decimal(i),
        )
    await db_session.commit()

    response = await client.get(f"/api/v1/projects/{project.id}/board")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 501
    assert body["truncated"] is True
    returned_count = sum(len(column["tasks"]) for column in body["columns"])
    assert returned_count == 500


@pytest.mark.parametrize(
    ("role", "expected_status"),
    [(Role.MANAGER, 200), (Role.ADMIN, 200), (Role.MEMBER, 403)],
)
async def test_reorder_via_patch_persists_board_position(
    client: AsyncClient, fake_verifier, db_session, role: Role, expected_status: int
) -> None:
    """Decision 1: no dedicated reorder endpoint — the client computes the
    midpoint and PATCHes it as an ordinary task field. A MEMBER who is
    neither the assignee nor creator still can't reorder someone else's
    task (same task-edit rule as any other field)."""
    owner_actor = await login_as(client, fake_verifier, db_session, role=Role.OWNER)
    project = await make_project(
        db_session, organization=owner_actor.organization, owner=owner_actor.membership
    )
    task = await make_task(
        db_session,
        organization=owner_actor.organization,
        created_by=owner_actor.membership,
        project=project,
        board_position=Decimal("1"),
    )
    await db_session.commit()

    actor_user = await make_user(
        db_session, email=f"reorder-{role.value}-{owner_actor.organization.id}@x.com"
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

    response = await client.patch(
        f"/api/v1/tasks/{task.id}",
        json={"board_position": "1.5"},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == expected_status
    if expected_status == 200:
        assert response.json()["board_position"] == "1.5"


@pytest.mark.parametrize("bad_value", ["NaN", "Infinity", "-Infinity", "not-a-number"])
async def test_reorder_rejects_non_finite_board_position(
    client: AsyncClient, fake_verifier, db_session, bad_value: str
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.MEMBER)
    create_response = await client.post(
        "/api/v1/tasks",
        json={"title": "Reorder me"},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    task_id = create_response.json()["id"]

    response = await client.patch(
        f"/api/v1/tasks/{task_id}",
        json={"board_position": bad_value},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == 422


async def test_reorder_rejects_null_board_position(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.MEMBER)
    create_response = await client.post(
        "/api/v1/tasks",
        json={"title": "Reorder me"},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    task_id = create_response.json()["id"]

    response = await client.patch(
        f"/api/v1/tasks/{task_id}",
        json={"board_position": None},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == 422

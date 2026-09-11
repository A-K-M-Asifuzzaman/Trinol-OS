from __future__ import annotations

from datetime import date, timedelta

import pytest
from httpx import AsyncClient

from tests.factories import make_membership, make_organization, make_project, make_task, make_user
from tests.helpers import login_as
from trinol.core.authz.permissions import Role
from trinol.modules.work.models import ProjectStatus, TaskStatus

pytestmark = pytest.mark.usefixtures("db_session")


async def test_active_projects_count_counts_only_active_status(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.MEMBER)
    await make_project(
        db_session,
        organization=actor.organization,
        owner=actor.membership,
        status=ProjectStatus.ACTIVE,
    )
    await make_project(
        db_session,
        organization=actor.organization,
        owner=actor.membership,
        status=ProjectStatus.PLANNING,
    )
    await make_project(
        db_session,
        organization=actor.organization,
        owner=actor.membership,
        status=ProjectStatus.COMPLETED,
    )
    await db_session.commit()

    response = await client.get("/api/v1/projects/analytics")
    assert response.status_code == 200
    assert response.json()["active_projects_count"] == 1


async def test_task_completion_rate_excludes_cancelled_tasks(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    """Phase 7 plan decision 2: DONE / (total - CANCELLED)."""
    actor = await login_as(client, fake_verifier, db_session, role=Role.MEMBER)
    await make_task(
        db_session,
        organization=actor.organization,
        created_by=actor.membership,
        status=TaskStatus.DONE,
    )
    await make_task(
        db_session,
        organization=actor.organization,
        created_by=actor.membership,
        status=TaskStatus.TODO,
    )
    await make_task(
        db_session,
        organization=actor.organization,
        created_by=actor.membership,
        status=TaskStatus.CANCELLED,
    )
    await db_session.commit()

    response = await client.get("/api/v1/projects/analytics")
    assert response.status_code == 200
    assert response.json()["task_completion_rate"] == pytest.approx(0.5)


async def test_task_completion_rate_is_null_with_no_non_cancelled_tasks(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.MEMBER)
    await make_task(
        db_session,
        organization=actor.organization,
        created_by=actor.membership,
        status=TaskStatus.CANCELLED,
    )
    await db_session.commit()

    response = await client.get("/api/v1/projects/analytics")
    assert response.status_code == 200
    assert response.json()["task_completion_rate"] is None


async def test_overdue_tasks_count_excludes_done_and_cancelled(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    """Phase 7 plan decision 3: same predicate shape as Invoice.is_overdue
    (open status AND due_date < today)."""
    actor = await login_as(client, fake_verifier, db_session, role=Role.MEMBER)
    yesterday = date.today() - timedelta(days=1)
    await make_task(
        db_session,
        organization=actor.organization,
        created_by=actor.membership,
        status=TaskStatus.TODO,
        due_date=yesterday,
    )
    # Excluded: overdue-shaped due_date, but DONE.
    await make_task(
        db_session,
        organization=actor.organization,
        created_by=actor.membership,
        status=TaskStatus.DONE,
        due_date=yesterday,
    )
    # Excluded: overdue-shaped due_date, but CANCELLED.
    await make_task(
        db_session,
        organization=actor.organization,
        created_by=actor.membership,
        status=TaskStatus.CANCELLED,
        due_date=yesterday,
    )
    # Excluded: open status, but due in the future.
    await make_task(
        db_session,
        organization=actor.organization,
        created_by=actor.membership,
        status=TaskStatus.TODO,
        due_date=date.today() + timedelta(days=1),
    )
    await db_session.commit()

    response = await client.get("/api/v1/projects/analytics")
    assert response.status_code == 200
    assert response.json()["overdue_tasks_count"] == 1


async def test_per_project_breakdown_includes_a_project_with_zero_tasks(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.MEMBER)
    project = await make_project(
        db_session, organization=actor.organization, owner=actor.membership, name="Empty Project"
    )
    await db_session.commit()

    response = await client.get("/api/v1/projects/analytics")
    assert response.status_code == 200
    rows = {row["project_id"]: row for row in response.json()["projects"]}
    assert str(project.id) in rows
    assert rows[str(project.id)]["task_completion_rate"] is None
    assert rows[str(project.id)]["overdue_tasks_count"] == 0


async def test_analytics_is_org_scoped(client: AsyncClient, fake_verifier, db_session) -> None:
    other_org = await make_organization(db_session)
    other_owner = await make_user(db_session, email=f"owner-{other_org.id}@x.com")
    other_actor = await make_membership(
        db_session, organization=other_org, user=other_owner, role=Role.MEMBER
    )
    await make_project(
        db_session, organization=other_org, owner=other_actor, status=ProjectStatus.ACTIVE
    )
    await make_task(
        db_session, organization=other_org, created_by=other_actor, status=TaskStatus.DONE
    )
    await db_session.commit()

    await login_as(client, fake_verifier, db_session, role=Role.MEMBER)
    response = await client.get("/api/v1/projects/analytics")
    assert response.status_code == 200
    body = response.json()
    assert body["active_projects_count"] == 0
    assert body["task_completion_rate"] is None
    assert body["overdue_tasks_count"] == 0
    assert body["projects"] == []

from __future__ import annotations

import asyncio

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from tests.factories import (
    make_membership,
    make_organization,
    make_project,
    make_project_member,
    make_user,
)
from tests.helpers import login_as, login_as_existing
from trinol.core.authz.permissions import Role
from trinol.core.db.engine import get_session_factory
from trinol.core.errors import ConflictError
from trinol.modules.identity.models import Membership, User
from trinol.modules.work.models import Project, ProjectHealth, ProjectMember, ProjectStatus
from trinol.modules.work.services.project_service import (
    archive_project,
    create_project,
    update_project,
)

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


async def test_concurrent_duplicate_project_code_only_one_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Both writers pass the pre-check; the unique constraint decides the race."""
    session_factory = get_session_factory()
    setup_session = session_factory()
    try:
        org = await make_organization(setup_session)
        user = await make_user(setup_session, email=f"project-race-{org.id}@x.com")
        actor = await make_membership(setup_session, organization=org, user=user, role=Role.OWNER)
        await setup_session.commit()
        org_id, user_id, actor_id = org.id, user.id, actor.id
    finally:
        await setup_session.close()

    session_1, session_2 = session_factory(), session_factory()
    arrived = 0
    both_prechecked = asyncio.Event()
    arrival_lock = asyncio.Lock()

    async def synchronize_project_code_precheck(original_execute, statement, *args, **kwargs):
        nonlocal arrived
        result = await original_execute(statement, *args, **kwargs)
        if "projects.project_code" in str(statement):
            async with arrival_lock:
                arrived += 1
                if arrived == 2:
                    both_prechecked.set()
            await both_prechecked.wait()
        return result

    original_1, original_2 = session_1.execute, session_2.execute

    async def execute_1(statement, *args, **kwargs):
        return await synchronize_project_code_precheck(original_1, statement, *args, **kwargs)

    async def execute_2(statement, *args, **kwargs):
        return await synchronize_project_code_precheck(original_2, statement, *args, **kwargs)

    monkeypatch.setattr(session_1, "execute", execute_1)
    monkeypatch.setattr(session_2, "execute", execute_2)

    try:
        actor_1 = (
            await original_1(
                select(Membership).where(
                    Membership.organization_id == org_id, Membership.id == actor_id
                )
            )
        ).scalar_one()
        actor_2 = (
            await original_2(
                select(Membership).where(
                    Membership.organization_id == org_id, Membership.id == actor_id
                )
            )
        ).scalar_one()

        async def create_one(db, actor):
            return await create_project(
                db,
                organization_id=org_id,
                actor=actor,
                project_code="RACE",
                name="Race",
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

        results = await asyncio.gather(
            create_one(session_1, actor_1),
            create_one(session_2, actor_2),
            return_exceptions=True,
        )
        assert sum(not isinstance(result, Exception) for result in results) == 1
        failures = [result for result in results if isinstance(result, Exception)]
        assert len(failures) == 1 and isinstance(failures[0], ConflictError)
    finally:
        await session_1.close()
        await session_2.close()
        cleanup = session_factory()
        try:
            await cleanup.execute(
                delete(ProjectMember).where(ProjectMember.organization_id == org_id)
            )
            await cleanup.execute(delete(Project).where(Project.organization_id == org_id))
            await cleanup.execute(delete(Membership).where(Membership.organization_id == org_id))
            await cleanup.execute(delete(User).where(User.id == user_id))
            # Organization (and its activity_events rows) is deliberately left
            # in place: Stage 7 now writes an activity_events row on project
            # create/update, and that table's append-only guarantee (migration
            # 0001) revokes UPDATE/DELETE from trinol_app entirely, which the
            # organizations FK (ON DELETE RESTRICT) then blocks anyway. Each
            # test uses a fresh uuid7 org id, so the orphaned row causes no
            # collision on rerun.
            await cleanup.commit()
        finally:
            await cleanup.close()


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


@pytest.mark.parametrize("field", ["project_code", "name", "status", "health", "currency"])
async def test_patch_rejects_null_for_required_fields(
    client: AsyncClient, fake_verifier, db_session, field: str
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.OWNER)
    project = await make_project(
        db_session, organization=actor.organization, owner=actor.membership
    )
    await db_session.commit()
    response = await client.patch(
        f"/api/v1/projects/{project.id}",
        json={field: None},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == 422


@pytest.mark.parametrize(
    ("initial", "update"),
    [
        ({"start_date": "2026-06-01"}, {"deadline": "2026-01-01"}),
        ({"deadline": "2026-06-01"}, {"start_date": "2026-12-01"}),
    ],
)
async def test_patch_validates_dates_against_stored_counterpart(
    client: AsyncClient, fake_verifier, db_session, initial: dict[str, str], update: dict[str, str]
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.OWNER)
    created = await client.post(
        "/api/v1/projects",
        json={"project_code": "DATES", "name": "Dates", **initial},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    response = await client.patch(
        f"/api/v1/projects/{created.json()['id']}",
        json=update,
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == 422


@pytest.mark.parametrize("budget", [123.45, "1234567890123.45", "1.234"])
async def test_budget_requires_bounded_decimal_string(
    client: AsyncClient, fake_verifier, db_session, budget: object
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.OWNER)
    response = await client.post(
        "/api/v1/projects",
        json={"project_code": "BUDGET", "name": "Budget", "budget": budget},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == 422


async def test_budget_decimal_string_round_trips_as_string(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.OWNER)
    response = await client.post(
        "/api/v1/projects",
        json={"project_code": "BUDGET", "name": "Budget", "budget": "123456789012.34"},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == 201
    assert response.json()["budget"] == "123456789012.34"


async def test_non_project_code_integrity_error_is_not_mislabeled(db_session) -> None:
    org = await make_organization(db_session)
    user = await make_user(db_session, email=f"integrity-{org.id}@x.com")
    actor = await make_membership(db_session, organization=org, user=user, role=Role.OWNER)
    project = await make_project(db_session, organization=org, owner=actor)
    await db_session.commit()

    with pytest.raises(IntegrityError):
        await update_project(
            db_session,
            organization_id=org.id,
            actor=actor,
            project_id=project.id,
            updates={"name": None},
        )


async def test_patch_duplicate_project_code_is_conflict(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.OWNER)
    first = await make_project(
        db_session, organization=actor.organization, owner=actor.membership, project_code="FIRST"
    )
    second = await make_project(
        db_session, organization=actor.organization, owner=actor.membership, project_code="SECOND"
    )
    await db_session.commit()

    response = await client.patch(
        f"/api/v1/projects/{second.id}",
        json={"project_code": first.project_code},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == 409


async def test_update_and_archive_return_trigger_refreshed_updated_at() -> None:
    session_factory = get_session_factory()
    session = session_factory()
    try:
        org = await make_organization(session)
        user = await make_user(session, email=f"timestamp-{org.id}@x.com")
        actor = await make_membership(session, organization=org, user=user, role=Role.OWNER)
        await session.commit()
        org_id, user_id = org.id, user.id

        project = await create_project(
            session,
            organization_id=org_id,
            actor=actor,
            project_code="TIMESTAMP",
            name="Timestamp",
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
        created_updated_at = project.updated_at
        await asyncio.sleep(0.001)
        project = await update_project(
            session,
            organization_id=org_id,
            actor=actor,
            project_id=project.id,
            updates={"name": "Updated"},
        )
        assert project.updated_at > created_updated_at

        updated_at = project.updated_at
        await asyncio.sleep(0.001)
        project = await archive_project(
            session,
            organization_id=org_id,
            actor=actor,
            project_id=project.id,
        )
        assert project.updated_at > updated_at
    finally:
        await session.close()
        cleanup = session_factory()
        try:
            await cleanup.execute(
                delete(ProjectMember).where(ProjectMember.organization_id == org_id)
            )
            await cleanup.execute(delete(Project).where(Project.organization_id == org_id))
            await cleanup.execute(delete(Membership).where(Membership.organization_id == org_id))
            await cleanup.execute(delete(User).where(User.id == user_id))
            # Organization (and its activity_events rows) is deliberately left
            # in place: Stage 7 now writes an activity_events row on project
            # create/update, and that table's append-only guarantee (migration
            # 0001) revokes UPDATE/DELETE from trinol_app entirely, which the
            # organizations FK (ON DELETE RESTRICT) then blocks anyway. Each
            # test uses a fresh uuid7 org id, so the orphaned row causes no
            # collision on rerun.
            await cleanup.commit()
        finally:
            await cleanup.close()


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

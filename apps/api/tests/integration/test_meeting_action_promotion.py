from __future__ import annotations

import asyncio
from datetime import date

import pytest
from dotenv import dotenv_values
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine

from tests.factories import (
    make_meeting,
    make_meeting_action,
    make_membership,
    make_organization,
    make_project,
    make_user,
)
from tests.helpers import login_as, login_as_existing
from trinol.core.authz.permissions import Role
from trinol.core.config import _ENV_FILE
from trinol.core.db.engine import get_session_factory
from trinol.core.errors import ConflictError
from trinol.modules.identity.models import Membership, Organization, User
from trinol.modules.meetings.models import Meeting, MeetingAction
from trinol.modules.meetings.services.meeting_action_service import promote_action
from trinol.modules.work.models import Task
from trinol.platform.activity import list_feed
from trinol.platform.models import ActivityEvent

# ARCHITECTURE.md §3's one documented cross-module write: MeetingAction ->
# Task, one transaction in meetings.services.meeting_action_service.
# promote_action. Gated by can_write_meeting (creator or MANAGER+), same
# rule as every other meeting-content write.

pytestmark = pytest.mark.usefixtures("db_session")


async def test_creator_can_promote_an_action_item(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.MEMBER)
    meeting = await make_meeting(
        db_session, organization=actor.organization, created_by=actor.membership
    )
    action = await make_meeting_action(
        db_session, meeting=meeting, description="Send the proposal."
    )
    await db_session.commit()

    response = await client.post(
        f"/api/v1/meetings/{meeting.id}/actions/{action.id}/promote",
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == 201
    task = response.json()
    assert task["title"] == "Send the proposal."
    assert task["status"] == "TODO"
    assert task["priority"] == "MEDIUM"

    action_response = await client.get(f"/api/v1/meetings/{meeting.id}/actions")
    promoted = next(a for a in action_response.json()["items"] if a["id"] == str(action.id))
    assert promoted["task_id"] == task["id"]


async def test_promotion_maps_owner_due_date_and_meeting_project(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.MANAGER)
    project = await make_project(
        db_session, organization=actor.organization, owner=actor.membership
    )
    meeting = await make_meeting(
        db_session, organization=actor.organization, created_by=actor.membership, project=project
    )
    owner_user = await make_user(db_session, email=f"promote-owner-{actor.organization.id}@x.com")
    owner_membership = await make_membership(
        db_session, organization=actor.organization, user=owner_user, role=Role.MEMBER
    )
    action = await make_meeting_action(
        db_session,
        meeting=meeting,
        owner=owner_membership,
        description="Follow up.",
        due_date=date(2026, 12, 1),
    )
    await db_session.commit()

    response = await client.post(
        f"/api/v1/meetings/{meeting.id}/actions/{action.id}/promote",
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == 201
    task = response.json()
    assert task["assignee_id"] == str(owner_membership.user_id)
    assert task["due_date"] == "2026-12-01"
    assert task["project_id"] == str(project.id)
    assert task["created_by"] == str(actor.membership.user_id)


async def test_promotion_records_both_activity_events(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.MEMBER)
    meeting = await make_meeting(
        db_session, organization=actor.organization, created_by=actor.membership
    )
    action = await make_meeting_action(db_session, meeting=meeting)
    await db_session.commit()

    response = await client.post(
        f"/api/v1/meetings/{meeting.id}/actions/{action.id}/promote",
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == 201
    task_id = response.json()["id"]

    feed_rows = await list_feed(db_session, organization_id=actor.organization.id)
    events = {e.event for e in feed_rows}
    assert "meeting_action.promoted" in events
    assert "task.created" in events
    task_created = next(e for e in feed_rows if e.event == "task.created")
    assert str(task_created.entity_id) == task_id


async def test_second_promotion_of_the_same_action_is_rejected(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.MEMBER)
    meeting = await make_meeting(
        db_session, organization=actor.organization, created_by=actor.membership
    )
    action = await make_meeting_action(db_session, meeting=meeting)
    await db_session.commit()

    first = await client.post(
        f"/api/v1/meetings/{meeting.id}/actions/{action.id}/promote",
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert first.status_code == 201

    second = await client.post(
        f"/api/v1/meetings/{meeting.id}/actions/{action.id}/promote",
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert second.status_code == 409

    tasks_result = await db_session.execute(
        select(Task).where(Task.organization_id == actor.organization.id)
    )
    assert len(tasks_result.scalars().all()) == 1, (
        "double-promotion must never create a second task"
    )


async def test_non_creator_member_cannot_promote_an_action_item(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    creator_actor = await login_as(client, fake_verifier, db_session, role=Role.MEMBER)
    meeting = await make_meeting(
        db_session, organization=creator_actor.organization, created_by=creator_actor.membership
    )
    action = await make_meeting_action(db_session, meeting=meeting)
    outsider_user = await make_user(
        db_session, email=f"promote-outsider-{creator_actor.organization.id}@x.com"
    )
    outsider_membership = await make_membership(
        db_session, organization=creator_actor.organization, user=outsider_user, role=Role.MEMBER
    )
    await db_session.commit()

    outsider = await login_as_existing(
        client,
        fake_verifier,
        user=outsider_user,
        membership=outsider_membership,
        organization=creator_actor.organization,
    )
    response = await client.post(
        f"/api/v1/meetings/{meeting.id}/actions/{action.id}/promote",
        headers={"X-CSRF-Token": outsider.csrf_token},
    )
    assert response.status_code == 403


async def test_promote_action_in_another_org_is_404(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    other_org = await make_organization(db_session)
    other_owner_user = await make_user(db_session, email=f"promote-other-{other_org.id}@x.com")
    other_owner_membership = await make_membership(
        db_session, organization=other_org, user=other_owner_user, role=Role.OWNER
    )
    other_meeting = await make_meeting(
        db_session, organization=other_org, created_by=other_owner_membership
    )
    other_action = await make_meeting_action(db_session, meeting=other_meeting)
    await db_session.commit()

    actor = await login_as(client, fake_verifier, db_session, role=Role.ADMIN)
    response = await client.post(
        f"/api/v1/meetings/{other_meeting.id}/actions/{other_action.id}/promote",
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == 404


async def test_promotion_is_rolled_back_atomically_if_an_error_occurs_after_the_flush(
    db_session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Codex-review-shaped regression test, mirroring convert_lead's own
    atomicity guarantee: promote_action must not call task_service.
    create_task() (which self-commits) precisely so that an exception
    anywhere before its own final db.commit() rolls back the whole thing,
    including the already-flushed-but-uncommitted Task row. Forces the
    second record() call (task.created, which runs after the Task is
    flushed and action.task_id is set in memory) to raise, then confirms
    no Task row exists and the action's task_id was never persisted."""
    import trinol.modules.meetings.services.meeting_action_service as service_module

    org = await make_organization(db_session)
    user = await make_user(db_session, email=f"atomic-{org.id}@x.com")
    actor = await make_membership(db_session, organization=org, user=user, role=Role.MEMBER)
    meeting = await make_meeting(db_session, organization=org, created_by=actor)
    action = await make_meeting_action(db_session, meeting=meeting, description="Atomic check.")
    await db_session.commit()
    # Captured before the rollback below expires every attribute on these
    # objects (rollback() always expires, regardless of expire_on_commit) —
    # a bare post-rollback attribute access on an AsyncSession object raises
    # MissingGreenlet, since the implicit reload has no async context here.
    org_id, meeting_id, action_id = org.id, meeting.id, action.id

    call_count = 0
    original_record = service_module.record

    async def _flaky_record(db, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            raise RuntimeError("simulated failure after the Task was flushed")
        return await original_record(db, **kwargs)

    monkeypatch.setattr(service_module, "record", _flaky_record)

    with pytest.raises(RuntimeError):
        await promote_action(
            db_session,
            organization_id=org_id,
            actor=actor,
            meeting_id=meeting_id,
            action_id=action_id,
        )
    await db_session.rollback()

    tasks_result = await db_session.execute(select(Task).where(Task.organization_id == org_id))
    assert tasks_result.scalars().all() == [], "the flushed Task must not survive the rollback"

    action_result = await db_session.execute(
        select(MeetingAction).where(
            MeetingAction.organization_id == org_id, MeetingAction.id == action_id
        )
    )
    refreshed_action = action_result.scalar_one()
    assert refreshed_action.task_id is None, "task_id must not have been persisted either"


async def _cleanup_race_test_rows(session_factory, *, organization_id, user_id) -> None:
    """Same FK-ordered pattern test_meeting_participants.py's own race-test
    cleanup already established: MeetingAction (references both Meeting
    and, once promoted, Task via fk_meeting_actions_org_task_tasks) must be
    deleted before either — then Meeting, then Membership, then User, then
    Organization. ActivityEvent via the migrator role separately
    (ADR-0006)."""
    migration_url = dotenv_values(_ENV_FILE)["DATABASE_MIGRATION_URL"]
    assert migration_url is not None
    migrator_engine = create_async_engine(migration_url)
    try:
        async with migrator_engine.begin() as conn:
            await conn.execute(
                ActivityEvent.__table__.delete().where(
                    ActivityEvent.organization_id == organization_id
                )
            )
    finally:
        await migrator_engine.dispose()

    cleanup_session = session_factory()
    try:
        await cleanup_session.execute(
            MeetingAction.__table__.delete().where(MeetingAction.organization_id == organization_id)
        )
        await cleanup_session.execute(
            Task.__table__.delete().where(Task.organization_id == organization_id)
        )
        await cleanup_session.execute(
            Meeting.__table__.delete().where(Meeting.organization_id == organization_id)
        )
        await cleanup_session.execute(
            Membership.__table__.delete().where(Membership.organization_id == organization_id)
        )
        await cleanup_session.execute(User.__table__.delete().where(User.id == user_id))
        await cleanup_session.execute(
            Organization.__table__.delete().where(Organization.id == organization_id)
        )
        await cleanup_session.commit()
    finally:
        await cleanup_session.close()


async def test_concurrent_promotion_of_the_same_action_only_one_succeeds() -> None:
    """Codex-review-shaped regression test, mirroring convert_lead's own
    concurrent-conversion test exactly: two independent DB sessions,
    asyncio.gather, real commits outside the test-fixture rollback
    boundary — proving Postgres actually serializes the two attempts via
    the action row's own FOR UPDATE lock (get_meeting_action_in_org's
    for_update=True), not just that the two never race within one shared
    transaction."""
    session_factory = get_session_factory()

    setup_session = session_factory()
    try:
        org = await make_organization(setup_session)
        user = await make_user(setup_session, email=f"promote-race-{org.id}@x.com")
        actor = await make_membership(setup_session, organization=org, user=user, role=Role.MEMBER)
        meeting = await make_meeting(setup_session, organization=org, created_by=actor)
        action = await make_meeting_action(
            setup_session, meeting=meeting, description="Race check."
        )
        await setup_session.commit()
        org_id, actor_id, meeting_id, action_id, user_id = (
            org.id,
            actor.id,
            meeting.id,
            action.id,
            user.id,
        )
    finally:
        await setup_session.close()

    session_1 = session_factory()
    session_2 = session_factory()
    try:
        actor_1 = (
            await session_1.execute(
                select(Membership).where(
                    Membership.organization_id == org_id, Membership.id == actor_id
                )
            )
        ).scalar_one()
        actor_2 = (
            await session_2.execute(
                select(Membership).where(
                    Membership.organization_id == org_id, Membership.id == actor_id
                )
            )
        ).scalar_one()

        results = await asyncio.gather(
            promote_action(
                session_1,
                organization_id=org_id,
                actor=actor_1,
                meeting_id=meeting_id,
                action_id=action_id,
            ),
            promote_action(
                session_2,
                organization_id=org_id,
                actor=actor_2,
                meeting_id=meeting_id,
                action_id=action_id,
            ),
            return_exceptions=True,
        )

        successes = [r for r in results if not isinstance(r, Exception)]
        failures = [r for r in results if isinstance(r, Exception)]
        assert len(successes) == 1, f"expected exactly one success, got: {results}"
        assert len(failures) == 1
        assert isinstance(failures[0], ConflictError)

        tasks_remaining = (
            (await session_1.execute(select(Task).where(Task.organization_id == org_id)))
            .scalars()
            .all()
        )
        assert len(tasks_remaining) == 1, "the race must never produce two tasks"
    finally:
        await session_1.close()
        await session_2.close()
        await _cleanup_race_test_rows(session_factory, organization_id=org_id, user_id=user_id)

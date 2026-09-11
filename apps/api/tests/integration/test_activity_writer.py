from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from httpx import AsyncClient
from sqlalchemy import select

from tests.factories import (
    make_client,
    make_invitation,
    make_invoice,
    make_lead,
    make_meeting,
    make_meeting_action,
    make_meeting_decision,
    make_membership,
    make_organization,
    make_project,
    make_user,
)
from trinol.core.authz.permissions import Role
from trinol.core.ids import uuid7
from trinol.modules.crm.models import ClientStatus, LeadSource, LeadStage
from trinol.modules.crm.services.client_service import create_client
from trinol.modules.crm.services.lead_service import create_lead, update_lead
from trinol.modules.finance.models import ExpenseCategory, InvoiceStatus
from trinol.modules.finance.services.expense_service import (
    create_expense,
    delete_expense,
    update_expense,
)
from trinol.modules.finance.services.income_service import (
    create_income,
    delete_income,
    update_income,
)
from trinol.modules.finance.services.invoice_service import (
    LineItemInput,
    cancel_invoice,
    create_invoice,
    send_invoice,
    update_invoice,
)
from trinol.modules.finance.services.payment_service import record_payment
from trinol.modules.identity.identity_verifier import VerifiedIdentity
from trinol.modules.identity.models import MembershipStatus
from trinol.modules.identity.services.membership_service import change_role, remove_member
from trinol.modules.meetings.models import MeetingParticipantResponse
from trinol.modules.meetings.services.meeting_action_service import (
    create_action,
    delete_action,
    promote_action,
)
from trinol.modules.meetings.services.meeting_decision_service import (
    create_decision,
    delete_decision,
)
from trinol.modules.meetings.services.meeting_participant_service import (
    add_participant,
    remove_participant,
    update_participant_response,
)
from trinol.modules.meetings.services.meeting_service import create_meeting, delete_meeting
from trinol.modules.work.models import (
    ProjectHealth,
    ProjectStatus,
    RoleOnProject,
    TaskPriority,
    TaskStatus,
)
from trinol.modules.work.services.project_member_service import (
    add_project_member,
    remove_project_member,
)
from trinol.modules.work.services.project_service import create_project, update_project
from trinol.modules.work.services.task_comment_service import create_comment
from trinol.modules.work.services.task_service import create_task, update_task
from trinol.platform.activity import list_audit, list_feed, record
from trinol.platform.documents import (
    create_document_reference,
    delete_document_reference,
    update_document_reference,
)
from trinol.platform.file_storage.local import LocalFileStorage
from trinol.platform.models import ActivityEvent, DocumentKind

# ADR-0006: one append-only table serving both the activity feed
# (is_audit=false, none exist yet — Phase 1 has no work/CRM content) and the
# audit log (is_audit=true, exercised throughout this file).


async def test_record_writes_a_row_with_the_given_fields(db_session) -> None:
    org = await make_organization(db_session)
    user = await make_user(db_session)
    await db_session.commit()

    event = await record(
        db_session,
        organization_id=org.id,
        event="test.thing_happened",
        entity_type="user",
        entity_id=user.id,
        actor_id=user.id,
        metadata={"key": "value"},
        audit=True,
        ip="203.0.113.1",
    )
    await db_session.commit()

    refreshed = (
        await db_session.execute(
            select(ActivityEvent).where(
                ActivityEvent.organization_id == org.id, ActivityEvent.id == event.id
            )
        )
    ).scalar_one()
    assert refreshed.event == "test.thing_happened"
    assert refreshed.entity_type == "user"
    assert refreshed.entity_id == user.id
    assert refreshed.actor_id == user.id
    assert refreshed.event_metadata == {"key": "value"}
    assert refreshed.is_audit is True
    assert refreshed.ip == "203.0.113.1"


async def test_list_audit_returns_only_audit_rows(db_session) -> None:
    org = await make_organization(db_session)
    user = await make_user(db_session)
    await db_session.commit()

    await record(
        db_session,
        organization_id=org.id,
        event="test.audit_one",
        entity_type="user",
        entity_id=user.id,
        audit=True,
    )
    await record(
        db_session,
        organization_id=org.id,
        event="test.feed_one",
        entity_type="user",
        entity_id=user.id,
        audit=False,
    )
    await db_session.commit()

    audit_rows = await list_audit(db_session, organization_id=org.id)
    feed_rows = await list_feed(db_session, organization_id=org.id)

    assert [row.event for row in audit_rows] == ["test.audit_one"]
    assert [row.event for row in feed_rows] == ["test.feed_one"]


async def test_no_feed_events_exist_yet(db_session) -> None:
    """Phase 1 has no work/CRM content, so nothing should ever produce an
    is_audit=false row yet — every event this phase writes is audit-only."""
    org = await make_organization(db_session)
    await db_session.commit()
    assert await list_feed(db_session, organization_id=org.id) == []


def _identity(*, firebase_uid: str, email: str) -> VerifiedIdentity:
    return VerifiedIdentity(
        firebase_uid=firebase_uid,
        email=email,
        email_verified=True,
        sign_in_provider="password",
        full_name="Test Person",
        avatar_url=None,
    )


async def test_successful_login_writes_an_audit_event(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    org = await make_organization(db_session)
    user = await make_user(db_session, email="login@x.com")
    await make_membership(db_session, organization=org, user=user, role=Role.MEMBER)
    await db_session.commit()

    fake_verifier.register("tok", _identity(firebase_uid=user.firebase_uid, email=user.email))
    response = await client.post("/api/v1/auth/session", json={"id_token": "tok"})
    assert response.status_code == 200

    rows = await list_audit(db_session, organization_id=org.id)
    assert [row.event for row in rows] == ["auth.session.created"]
    assert rows[0].actor_id == user.id


async def test_inactive_membership_rejection_writes_an_audit_event(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    org = await make_organization(db_session)
    user = await make_user(db_session, email="inactive@x.com")
    await make_membership(db_session, organization=org, user=user, status=MembershipStatus.INACTIVE)
    await db_session.commit()

    fake_verifier.register("tok", _identity(firebase_uid=user.firebase_uid, email=user.email))
    response = await client.post("/api/v1/auth/session", json={"id_token": "tok"})
    assert response.status_code == 403

    rows = await list_audit(db_session, organization_id=org.id)
    assert [row.event for row in rows] == ["auth.exchange.rejected"]
    assert rows[0].event_metadata["reason"] == "membership_inactive"


async def test_expired_invitation_rejection_writes_an_audit_event(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    org = await make_organization(db_session)
    inviter = await make_user(db_session, email="inviter@x.com")
    invitation = await make_invitation(
        db_session,
        organization=org,
        email="expired@x.com",
        invited_by=inviter,
        expires_in=timedelta(days=-1),
    )
    await db_session.commit()

    fake_verifier.register("tok", _identity(firebase_uid=f"fb-{uuid7()}", email="expired@x.com"))
    response = await client.post("/api/v1/auth/session", json={"id_token": "tok"})
    assert response.status_code == 403

    rows = await list_audit(db_session, organization_id=org.id)
    assert [row.event for row in rows] == ["auth.exchange.rejected"]
    assert rows[0].entity_type == "invitation"
    assert rows[0].entity_id == invitation.id
    assert rows[0].event_metadata["reason"] == "invitation_expired"


async def test_unknown_identity_with_no_invitation_writes_no_event(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    """The one documented gap (AUTH.md §5): no organization is determinable
    here, and activity_events.organization_id is NOT NULL, so this rejection
    is logged (core/logging.py), not written to activity_events at all."""
    org = await make_organization(db_session)
    await db_session.commit()

    fake_verifier.register("tok", _identity(firebase_uid=f"fb-{uuid7()}", email="nobody@x.com"))
    response = await client.post("/api/v1/auth/session", json={"id_token": "tok"})
    assert response.status_code == 403

    assert await list_audit(db_session, organization_id=org.id) == []


async def test_role_change_writes_an_audit_event(db_session) -> None:
    org = await make_organization(db_session)
    owner_user = await make_user(db_session, email="owner@x.com")
    target_user = await make_user(db_session, email="target@x.com")
    owner = await make_membership(db_session, organization=org, user=owner_user, role=Role.OWNER)
    target = await make_membership(
        db_session, organization=org, user=target_user, role=Role.MANAGER
    )
    await db_session.commit()

    await change_role(
        db_session,
        organization_id=org.id,
        actor=owner,
        target_membership_id=target.id,
        new_role=Role.ADMIN,
    )

    rows = await list_audit(db_session, organization_id=org.id)
    assert [row.event for row in rows] == ["membership.role_changed"]
    assert rows[0].entity_id == target.id
    assert rows[0].actor_id == owner.user_id
    assert rows[0].event_metadata == {"from_role": "MANAGER", "to_role": "ADMIN"}


async def test_member_removal_writes_an_audit_event(db_session) -> None:
    org = await make_organization(db_session)
    owner_user = await make_user(db_session, email="owner2@x.com")
    target_user = await make_user(db_session, email="target2@x.com")
    owner = await make_membership(db_session, organization=org, user=owner_user, role=Role.OWNER)
    target = await make_membership(db_session, organization=org, user=target_user, role=Role.MEMBER)
    await db_session.commit()

    await remove_member(
        db_session, organization_id=org.id, actor=owner, target_membership_id=target.id
    )

    rows = await list_audit(db_session, organization_id=org.id)
    assert [row.event for row in rows] == ["membership.removed"]
    assert rows[0].entity_id == target.id
    assert rows[0].event_metadata == {"role": "MEMBER"}


# ROADMAP.md Phase 2 Stage 7 decision 2: ordinary feed content (is_audit=false)
# below; project_member add/remove stays audit-only (RBAC.md §3 guard 6) and
# must not show up in the feed.


async def test_create_project_writes_a_feed_event(db_session) -> None:
    org = await make_organization(db_session)
    user = await make_user(db_session, email="proj-owner@x.com")
    actor = await make_membership(db_session, organization=org, user=user, role=Role.OWNER)
    await db_session.commit()

    project = await create_project(
        db_session,
        organization_id=org.id,
        actor=actor,
        project_code="FEED",
        name="Feed Project",
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

    rows = await list_feed(db_session, organization_id=org.id)
    assert [row.event for row in rows] == ["project.created"]
    assert rows[0].entity_type == "project"
    assert rows[0].entity_id == project.id
    assert rows[0].is_audit is False
    assert await list_audit(db_session, organization_id=org.id) == []


async def test_project_status_change_writes_a_feed_event(db_session) -> None:
    org = await make_organization(db_session)
    user = await make_user(db_session, email="proj-status@x.com")
    actor = await make_membership(db_session, organization=org, user=user, role=Role.OWNER)
    await db_session.commit()
    project = await make_project(db_session, organization=org, owner=actor)
    await db_session.commit()

    await update_project(
        db_session,
        organization_id=org.id,
        actor=actor,
        project_id=project.id,
        updates={"status": ProjectStatus.ACTIVE},
    )

    rows = await list_feed(db_session, organization_id=org.id)
    assert [row.event for row in rows] == ["project.status_changed"]
    assert rows[0].event_metadata == {"from": "PLANNING", "to": "ACTIVE"}


async def test_project_update_without_status_change_writes_no_feed_event(db_session) -> None:
    org = await make_organization(db_session)
    user = await make_user(db_session, email="proj-noop@x.com")
    actor = await make_membership(db_session, organization=org, user=user, role=Role.OWNER)
    await db_session.commit()
    project = await make_project(db_session, organization=org, owner=actor)
    await db_session.commit()

    await update_project(
        db_session,
        organization_id=org.id,
        actor=actor,
        project_id=project.id,
        updates={"name": "Renamed"},
    )

    assert await list_feed(db_session, organization_id=org.id) == []


async def test_create_client_writes_a_feed_event(db_session) -> None:
    org = await make_organization(db_session)
    user = await make_user(db_session, email="client-owner@x.com")
    actor = await make_membership(db_session, organization=org, user=user, role=Role.OWNER)
    await db_session.commit()

    client = await create_client(
        db_session,
        organization_id=org.id,
        actor=actor,
        name="Feed Client",
        company=None,
        email=None,
        phone=None,
        website=None,
        address=None,
        notes=None,
        status=ClientStatus.ACTIVE,
        owner_id=None,
    )

    rows = await list_feed(db_session, organization_id=org.id)
    assert [row.event for row in rows] == ["client.created"]
    assert rows[0].entity_type == "client"
    assert rows[0].entity_id == client.id
    assert rows[0].is_audit is False
    assert await list_audit(db_session, organization_id=org.id) == []


async def test_create_lead_writes_a_feed_event(db_session) -> None:
    org = await make_organization(db_session)
    user = await make_user(db_session, email="lead-owner@x.com")
    actor = await make_membership(db_session, organization=org, user=user, role=Role.OWNER)
    await db_session.commit()

    lead = await create_lead(
        db_session,
        organization_id=org.id,
        actor=actor,
        name="Feed Lead",
        company=None,
        email="feed-lead@x.com",
        phone=None,
        source=LeadSource.WEBSITE,
        service=None,
        estimated_value=None,
        currency="USD",
        stage=LeadStage.NEW,
        assigned_to=None,
        next_follow_up=None,
        notes=None,
    )

    rows = await list_feed(db_session, organization_id=org.id)
    assert [row.event for row in rows] == ["lead.created"]
    assert rows[0].entity_type == "lead"
    assert rows[0].entity_id == lead.id
    assert rows[0].is_audit is False
    assert await list_audit(db_session, organization_id=org.id) == []


async def test_lead_stage_change_writes_a_feed_event(db_session) -> None:
    org = await make_organization(db_session)
    user = await make_user(db_session, email="lead-stage@x.com")
    actor = await make_membership(db_session, organization=org, user=user, role=Role.OWNER)
    await db_session.commit()
    lead = await make_lead(db_session, organization=org, email="stage-feed@x.com")
    await db_session.commit()

    await update_lead(
        db_session,
        organization_id=org.id,
        actor=actor,
        lead_id=lead.id,
        updates={"stage": LeadStage.CONTACTED},
    )

    rows = await list_feed(db_session, organization_id=org.id)
    assert [row.event for row in rows] == ["lead.stage_changed"]
    assert rows[0].event_metadata == {"from": "NEW", "to": "CONTACTED"}


async def test_lead_update_without_stage_change_writes_no_feed_event(db_session) -> None:
    org = await make_organization(db_session)
    user = await make_user(db_session, email="lead-noop@x.com")
    actor = await make_membership(db_session, organization=org, user=user, role=Role.OWNER)
    await db_session.commit()
    lead = await make_lead(db_session, organization=org, email="noop-feed@x.com")
    await db_session.commit()

    await update_lead(
        db_session,
        organization_id=org.id,
        actor=actor,
        lead_id=lead.id,
        updates={"notes": "Renamed"},
    )

    assert await list_feed(db_session, organization_id=org.id) == []


async def test_create_task_writes_a_feed_event(db_session) -> None:
    org = await make_organization(db_session)
    user = await make_user(db_session, email="task-create@x.com")
    actor = await make_membership(db_session, organization=org, user=user, role=Role.MEMBER)
    await db_session.commit()

    task = await create_task(
        db_session,
        organization_id=org.id,
        actor=actor,
        project_id=None,
        title="Feed Task",
        description=None,
        status=TaskStatus.TODO,
        priority=TaskPriority.MEDIUM,
        assignee_id=None,
        milestone_id=None,
        due_date=None,
        start_date=None,
        estimated_hours=None,
        actual_hours=None,
        tags=None,
    )

    rows = await list_feed(db_session, organization_id=org.id)
    assert [row.event for row in rows] == ["task.created"]
    assert rows[0].entity_type == "task"
    assert rows[0].entity_id == task.id


async def test_task_status_change_writes_a_feed_event(db_session) -> None:
    org = await make_organization(db_session)
    user = await make_user(db_session, email="task-status@x.com")
    actor = await make_membership(db_session, organization=org, user=user, role=Role.MEMBER)
    await db_session.commit()
    task = await create_task(
        db_session,
        organization_id=org.id,
        actor=actor,
        project_id=None,
        title="Status Task",
        description=None,
        status=TaskStatus.TODO,
        priority=TaskPriority.MEDIUM,
        assignee_id=None,
        milestone_id=None,
        due_date=None,
        start_date=None,
        estimated_hours=None,
        actual_hours=None,
        tags=None,
    )

    await update_task(
        db_session,
        organization_id=org.id,
        actor=actor,
        task_id=task.id,
        updates={"status": TaskStatus.IN_PROGRESS},
    )

    rows = await list_feed(db_session, organization_id=org.id)
    by_event = {row.event: row for row in rows}
    assert set(by_event) == {"task.created", "task.status_changed"}
    assert by_event["task.status_changed"].event_metadata == {"from": "TODO", "to": "IN_PROGRESS"}


async def test_task_completion_writes_a_completed_event_not_status_changed(db_session) -> None:
    org = await make_organization(db_session)
    user = await make_user(db_session, email="task-done@x.com")
    actor = await make_membership(db_session, organization=org, user=user, role=Role.MEMBER)
    await db_session.commit()
    task = await create_task(
        db_session,
        organization_id=org.id,
        actor=actor,
        project_id=None,
        title="Done Task",
        description=None,
        status=TaskStatus.TODO,
        priority=TaskPriority.MEDIUM,
        assignee_id=None,
        milestone_id=None,
        due_date=None,
        start_date=None,
        estimated_hours=None,
        actual_hours=None,
        tags=None,
    )

    await update_task(
        db_session,
        organization_id=org.id,
        actor=actor,
        task_id=task.id,
        updates={"status": TaskStatus.DONE},
    )

    rows = await list_feed(db_session, organization_id=org.id)
    by_event = {row.event: row for row in rows}
    assert set(by_event) == {"task.created", "task.completed"}
    assert by_event["task.completed"].event_metadata == {"from": "TODO"}


async def test_create_comment_writes_a_feed_event(db_session) -> None:
    org = await make_organization(db_session)
    user = await make_user(db_session, email="comment-create@x.com")
    actor = await make_membership(db_session, organization=org, user=user, role=Role.MEMBER)
    await db_session.commit()
    task = await create_task(
        db_session,
        organization_id=org.id,
        actor=actor,
        project_id=None,
        title="Commented Task",
        description=None,
        status=TaskStatus.TODO,
        priority=TaskPriority.MEDIUM,
        assignee_id=None,
        milestone_id=None,
        due_date=None,
        start_date=None,
        estimated_hours=None,
        actual_hours=None,
        tags=None,
    )

    comment = await create_comment(
        db_session, organization_id=org.id, actor=actor, task_id=task.id, body="Hello"
    )

    rows = await list_feed(db_session, organization_id=org.id)
    by_event = {row.event: row for row in rows}
    assert set(by_event) == {"task.created", "comment.created"}
    assert by_event["comment.created"].entity_type == "task_comment"
    assert by_event["comment.created"].entity_id == comment.id
    assert by_event["comment.created"].event_metadata == {"task_id": str(task.id)}


async def test_project_member_add_and_remove_write_audit_events_not_feed(db_session) -> None:
    org = await make_organization(db_session)
    owner_user = await make_user(db_session, email="member-owner@x.com")
    owner = await make_membership(db_session, organization=org, user=owner_user, role=Role.OWNER)
    target_user = await make_user(db_session, email="member-target@x.com")
    await make_membership(db_session, organization=org, user=target_user, role=Role.MEMBER)
    await db_session.commit()
    project = await make_project(db_session, organization=org, owner=owner)
    await db_session.commit()

    member = await add_project_member(
        db_session,
        organization_id=org.id,
        actor=owner,
        project_id=project.id,
        user_id=target_user.id,
        role_on_project=RoleOnProject.CONTRIBUTOR,
    )

    audit_rows = await list_audit(db_session, organization_id=org.id)
    assert [row.event for row in audit_rows] == ["project_member.added"]
    assert audit_rows[0].entity_type == "project_member"
    assert audit_rows[0].entity_id == member.id
    assert audit_rows[0].event_metadata == {
        "project_id": str(project.id),
        "user_id": str(target_user.id),
    }
    assert await list_feed(db_session, organization_id=org.id) == []

    await remove_project_member(
        db_session,
        organization_id=org.id,
        actor=owner,
        project_id=project.id,
        member_id=member.id,
    )

    audit_rows = await list_audit(db_session, organization_id=org.id)
    by_event = {row.event: row for row in audit_rows}
    assert set(by_event) == {"project_member.added", "project_member.removed"}
    assert by_event["project_member.removed"].entity_id == member.id
    assert by_event["project_member.removed"].event_metadata == {
        "project_id": str(project.id),
        "user_id": str(target_user.id),
    }
    assert await list_feed(db_session, organization_id=org.id) == []


async def test_create_meeting_writes_a_feed_event(db_session) -> None:
    org = await make_organization(db_session)
    user = await make_user(db_session, email="meeting-owner@x.com")
    actor = await make_membership(db_session, organization=org, user=user, role=Role.MEMBER)
    await db_session.commit()

    meeting = await create_meeting(
        db_session,
        organization_id=org.id,
        actor=actor,
        title="Feed Meeting",
        description=None,
        starts_at=datetime.now(UTC) + timedelta(days=1),
        ends_at=datetime.now(UTC) + timedelta(days=1, hours=1),
        client_id=None,
        project_id=None,
        meeting_url=None,
        location=None,
        notes=None,
    )

    rows = await list_feed(db_session, organization_id=org.id)
    assert [row.event for row in rows] == ["meeting.created"]
    assert rows[0].entity_type == "meeting"
    assert rows[0].entity_id == meeting.id
    assert rows[0].is_audit is False
    assert await list_audit(db_session, organization_id=org.id) == []


async def test_delete_meeting_writes_an_audit_event_not_feed(db_session) -> None:
    """ADR-0011: meetings are hard-deleted — the audit event is the only
    remaining record of who deleted it and when."""
    org = await make_organization(db_session)
    user = await make_user(db_session, email="meeting-deleter@x.com")
    actor = await make_membership(db_session, organization=org, user=user, role=Role.MEMBER)
    meeting = await make_meeting(db_session, organization=org, created_by=actor)
    await db_session.commit()
    meeting_id = meeting.id

    await delete_meeting(db_session, organization_id=org.id, actor=actor, meeting_id=meeting_id)

    audit_rows = await list_audit(db_session, organization_id=org.id)
    assert [row.event for row in audit_rows] == ["meeting.deleted"]
    assert audit_rows[0].entity_type == "meeting"
    assert audit_rows[0].entity_id == meeting_id
    assert await list_feed(db_session, organization_id=org.id) == []


async def test_meeting_participant_add_and_remove_write_audit_events_not_feed(db_session) -> None:
    """Same reasoning as project_member.added/removed: adding or removing a
    participant changes who can see the meeting (RBAC.md §3), so it's
    always is_audit=true, never ordinary feed content."""
    org = await make_organization(db_session)
    creator_user = await make_user(db_session, email="participant-creator@x.com")
    creator = await make_membership(
        db_session, organization=org, user=creator_user, role=Role.MEMBER
    )
    target_user = await make_user(db_session, email="participant-target@x.com")
    await make_membership(db_session, organization=org, user=target_user, role=Role.MEMBER)
    await db_session.commit()
    meeting = await make_meeting(db_session, organization=org, created_by=creator)
    await db_session.commit()

    participant = await add_participant(
        db_session,
        organization_id=org.id,
        actor=creator,
        meeting_id=meeting.id,
        user_id=target_user.id,
        external_email=None,
    )

    audit_rows = await list_audit(db_session, organization_id=org.id)
    assert [row.event for row in audit_rows] == ["meeting_participant.added"]
    assert audit_rows[0].entity_type == "meeting_participant"
    assert audit_rows[0].entity_id == participant.id
    assert await list_feed(db_session, organization_id=org.id) == []

    await remove_participant(
        db_session,
        organization_id=org.id,
        actor=creator,
        meeting_id=meeting.id,
        participant_id=participant.id,
    )

    audit_rows = await list_audit(db_session, organization_id=org.id)
    by_event = {row.event: row for row in audit_rows}
    assert set(by_event) == {"meeting_participant.added", "meeting_participant.removed"}
    assert by_event["meeting_participant.removed"].entity_id == participant.id
    assert await list_feed(db_session, organization_id=org.id) == []


async def test_update_participant_response_writes_no_activity_event(db_session) -> None:
    """Phase 4 Stage 1 decision: unlike add/remove, changing your own RSVP
    doesn't change who can see the meeting, so it's neither an audit event
    nor ordinary feed content — no event at all."""
    org = await make_organization(db_session)
    creator_user = await make_user(db_session, email="response-creator@x.com")
    creator = await make_membership(
        db_session, organization=org, user=creator_user, role=Role.MEMBER
    )
    meeting = await make_meeting(db_session, organization=org, created_by=creator)
    await db_session.commit()
    participant = await add_participant(
        db_session,
        organization_id=org.id,
        actor=creator,
        meeting_id=meeting.id,
        user_id=creator_user.id,
        external_email=None,
    )

    await update_participant_response(
        db_session,
        organization_id=org.id,
        actor=creator,
        meeting_id=meeting.id,
        participant_id=participant.id,
        response=MeetingParticipantResponse.ACCEPTED,
    )

    feed_before = await list_feed(db_session, organization_id=org.id)
    audit_before = await list_audit(db_session, organization_id=org.id)
    # Exactly the one audit row from add_participant above — the response
    # update itself added nothing to either table.
    assert [row.event for row in audit_before] == ["meeting_participant.added"]
    assert feed_before == []


async def test_create_decision_writes_a_feed_event(db_session) -> None:
    org = await make_organization(db_session)
    user = await make_user(db_session, email="decision-owner@x.com")
    actor = await make_membership(db_session, organization=org, user=user, role=Role.MEMBER)
    meeting = await make_meeting(db_session, organization=org, created_by=actor)
    await db_session.commit()

    decision = await create_decision(
        db_session,
        organization_id=org.id,
        actor=actor,
        meeting_id=meeting.id,
        body="Feed decision.",
    )

    rows = await list_feed(db_session, organization_id=org.id)
    assert [row.event for row in rows] == ["meeting_decision.created"]
    assert rows[0].entity_type == "meeting_decision"
    assert rows[0].entity_id == decision.id
    assert rows[0].is_audit is False
    assert await list_audit(db_session, organization_id=org.id) == []


async def test_delete_decision_writes_an_audit_event_not_feed(db_session) -> None:
    """ADR-0011: hard delete, recorded as an audit event — a blanket rule,
    not limited to visibility-relevant deletes."""
    org = await make_organization(db_session)
    user = await make_user(db_session, email="decision-deleter@x.com")
    actor = await make_membership(db_session, organization=org, user=user, role=Role.MEMBER)
    meeting = await make_meeting(db_session, organization=org, created_by=actor)
    decision = await make_meeting_decision(db_session, meeting=meeting, decided_by=actor)
    await db_session.commit()
    decision_id = decision.id

    await delete_decision(
        db_session,
        organization_id=org.id,
        actor=actor,
        meeting_id=meeting.id,
        decision_id=decision_id,
    )

    audit_rows = await list_audit(db_session, organization_id=org.id)
    by_event = {row.event: row for row in audit_rows}
    assert set(by_event) == {"meeting_decision.deleted"}
    assert by_event["meeting_decision.deleted"].entity_id == decision_id
    assert await list_feed(db_session, organization_id=org.id) == []


async def test_create_action_writes_a_feed_event(db_session) -> None:
    org = await make_organization(db_session)
    user = await make_user(db_session, email="action-owner@x.com")
    actor = await make_membership(db_session, organization=org, user=user, role=Role.MEMBER)
    meeting = await make_meeting(db_session, organization=org, created_by=actor)
    await db_session.commit()

    action = await create_action(
        db_session,
        organization_id=org.id,
        actor=actor,
        meeting_id=meeting.id,
        description="Feed action.",
        owner_id=None,
        due_date=None,
    )

    rows = await list_feed(db_session, organization_id=org.id)
    assert [row.event for row in rows] == ["meeting_action.created"]
    assert rows[0].entity_type == "meeting_action"
    assert rows[0].entity_id == action.id
    assert rows[0].is_audit is False
    assert await list_audit(db_session, organization_id=org.id) == []


async def test_delete_action_writes_an_audit_event_not_feed(db_session) -> None:
    """ADR-0011: hard delete, recorded as an audit event."""
    org = await make_organization(db_session)
    user = await make_user(db_session, email="action-deleter@x.com")
    actor = await make_membership(db_session, organization=org, user=user, role=Role.MEMBER)
    meeting = await make_meeting(db_session, organization=org, created_by=actor)
    action = await make_meeting_action(db_session, meeting=meeting)
    await db_session.commit()
    action_id = action.id

    await delete_action(
        db_session, organization_id=org.id, actor=actor, meeting_id=meeting.id, action_id=action_id
    )

    audit_rows = await list_audit(db_session, organization_id=org.id)
    by_event = {row.event: row for row in audit_rows}
    assert set(by_event) == {"meeting_action.deleted"}
    assert by_event["meeting_action.deleted"].entity_id == action_id
    assert await list_feed(db_session, organization_id=org.id) == []


async def test_promote_action_writes_both_as_feed_events(db_session) -> None:
    """ARCHITECTURE.md §3's one cross-module write: meeting_action.promoted
    and task.created both land as ordinary feed content, in the same
    transaction, matching create_task's own is_audit=false precedent."""
    org = await make_organization(db_session)
    user = await make_user(db_session, email="promote-owner@x.com")
    actor = await make_membership(db_session, organization=org, user=user, role=Role.MEMBER)
    meeting = await make_meeting(db_session, organization=org, created_by=actor)
    action = await make_meeting_action(db_session, meeting=meeting, description="Promote me.")
    await db_session.commit()

    task = await promote_action(
        db_session, organization_id=org.id, actor=actor, meeting_id=meeting.id, action_id=action.id
    )

    rows = await list_feed(db_session, organization_id=org.id)
    by_event = {row.event: row for row in rows}
    assert set(by_event) == {"meeting_action.promoted", "task.created"}
    assert by_event["meeting_action.promoted"].entity_id == action.id
    assert by_event["task.created"].entity_id == task.id
    assert await list_audit(db_session, organization_id=org.id) == []


# Phase 5 Stage 9: every finance event named in the plan (income/expense
# create+delete, invoice create/send/cancel, payment.recorded) was wired
# inline in its own stage rather than deferred to a retrofit pass here
# (Phase 2's pattern, not Phase 3's — same decision Phase 4 Stage 2 already
# made for meeting.created). This is the verification pass the plan itself
# calls for, not new wiring.


async def test_create_income_writes_a_feed_event(db_session) -> None:
    org = await make_organization(db_session)
    user = await make_user(db_session, email="income-owner@x.com")
    actor = await make_membership(db_session, organization=org, user=user, role=Role.OWNER)
    await db_session.commit()

    income = await create_income(
        db_session,
        organization_id=org.id,
        actor=actor,
        amount=Decimal("100.00"),
        currency="USD",
        source="Feed income",
        client_id=None,
        project_id=None,
        invoice_id=None,
        received_on=date.today(),
        payment_method="cash",
        reference=None,
        notes=None,
    )

    rows = await list_feed(db_session, organization_id=org.id)
    assert [row.event for row in rows] == ["income.created"]
    assert rows[0].entity_type == "income"
    assert rows[0].entity_id == income.id
    assert rows[0].is_audit is False
    assert await list_audit(db_session, organization_id=org.id) == []


async def test_income_update_writes_no_event(db_session) -> None:
    org = await make_organization(db_session)
    user = await make_user(db_session, email="income-noop@x.com")
    actor = await make_membership(db_session, organization=org, user=user, role=Role.OWNER)
    await db_session.commit()
    income = await create_income(
        db_session,
        organization_id=org.id,
        actor=actor,
        amount=Decimal("100.00"),
        currency="USD",
        source="Original",
        client_id=None,
        project_id=None,
        invoice_id=None,
        received_on=date.today(),
        payment_method="cash",
        reference=None,
        notes=None,
    )

    await update_income(
        db_session,
        organization_id=org.id,
        actor=actor,
        income_id=income.id,
        updates={"notes": "Reconciled"},
    )

    # The create above already wrote one feed row — assert the update added
    # no *additional* row rather than asserting an empty feed outright.
    rows = await list_feed(db_session, organization_id=org.id)
    assert [row.event for row in rows] == ["income.created"]


async def test_delete_income_writes_an_audit_event_not_feed(db_session) -> None:
    """ADR-0011: income is not one of the four soft-deleted entities — a
    hard delete, the audit event is the only remaining record."""
    org = await make_organization(db_session)
    user = await make_user(db_session, email="income-deleter@x.com")
    actor = await make_membership(db_session, organization=org, user=user, role=Role.OWNER)
    await db_session.commit()
    income = await create_income(
        db_session,
        organization_id=org.id,
        actor=actor,
        amount=Decimal("50.00"),
        currency="USD",
        source="To delete",
        client_id=None,
        project_id=None,
        invoice_id=None,
        received_on=date.today(),
        payment_method="cash",
        reference=None,
        notes=None,
    )
    income_id = income.id

    await delete_income(db_session, organization_id=org.id, actor=actor, income_id=income_id)

    audit_rows = await list_audit(db_session, organization_id=org.id)
    by_event = {row.event: row for row in audit_rows}
    assert set(by_event) == {"income.deleted"}
    assert by_event["income.deleted"].entity_id == income_id
    feed_rows = await list_feed(db_session, organization_id=org.id)
    assert [row.event for row in feed_rows] == ["income.created"]


async def test_create_expense_writes_a_feed_event(db_session) -> None:
    org = await make_organization(db_session)
    user = await make_user(db_session, email="expense-owner@x.com")
    actor = await make_membership(db_session, organization=org, user=user, role=Role.OWNER)
    await db_session.commit()

    expense = await create_expense(
        db_session,
        organization_id=org.id,
        actor=actor,
        amount=Decimal("40.00"),
        currency="USD",
        category=ExpenseCategory.SOFTWARE,
        description="Feed expense",
        vendor=None,
        spent_on=date.today(),
        payment_method="card",
        notes=None,
    )

    rows = await list_feed(db_session, organization_id=org.id)
    assert [row.event for row in rows] == ["expense.created"]
    assert rows[0].entity_type == "expense"
    assert rows[0].entity_id == expense.id
    assert rows[0].is_audit is False
    assert await list_audit(db_session, organization_id=org.id) == []


async def test_expense_update_writes_no_additional_event(db_session) -> None:
    org = await make_organization(db_session)
    user = await make_user(db_session, email="expense-noop@x.com")
    actor = await make_membership(db_session, organization=org, user=user, role=Role.OWNER)
    await db_session.commit()
    expense = await create_expense(
        db_session,
        organization_id=org.id,
        actor=actor,
        amount=Decimal("40.00"),
        currency="USD",
        category=ExpenseCategory.SOFTWARE,
        description="Original",
        vendor=None,
        spent_on=date.today(),
        payment_method="card",
        notes=None,
    )

    await update_expense(
        db_session,
        organization_id=org.id,
        actor=actor,
        expense_id=expense.id,
        updates={"notes": "Reconciled"},
    )

    rows = await list_feed(db_session, organization_id=org.id)
    assert [row.event for row in rows] == ["expense.created"]


async def test_delete_expense_writes_an_audit_event_not_feed(db_session, tmp_path) -> None:
    org = await make_organization(db_session)
    user = await make_user(db_session, email="expense-deleter@x.com")
    actor = await make_membership(db_session, organization=org, user=user, role=Role.OWNER)
    await db_session.commit()
    expense = await create_expense(
        db_session,
        organization_id=org.id,
        actor=actor,
        amount=Decimal("40.00"),
        currency="USD",
        category=ExpenseCategory.SOFTWARE,
        description="To delete",
        vendor=None,
        spent_on=date.today(),
        payment_method="card",
        notes=None,
    )
    expense_id = expense.id

    await delete_expense(
        db_session,
        organization_id=org.id,
        actor=actor,
        expense_id=expense_id,
        storage=LocalFileStorage(tmp_path),
    )

    audit_rows = await list_audit(db_session, organization_id=org.id)
    by_event = {row.event: row for row in audit_rows}
    assert set(by_event) == {"expense.deleted"}
    assert by_event["expense.deleted"].entity_id == expense_id
    feed_rows = await list_feed(db_session, organization_id=org.id)
    assert [row.event for row in feed_rows] == ["expense.created"]


async def test_create_invoice_writes_a_feed_event(db_session) -> None:
    org = await make_organization(db_session)
    user = await make_user(db_session, email="invoice-owner@x.com")
    actor = await make_membership(db_session, organization=org, user=user, role=Role.OWNER)
    client = await make_client(db_session, organization=org)
    await db_session.commit()

    pair = await create_invoice(
        db_session,
        organization_id=org.id,
        actor=actor,
        client_id=client.id,
        project_id=None,
        issue_date=date(2026, 1, 1),
        due_date=date(2026, 1, 15),
        currency="USD",
        items=[
            LineItemInput(description="Work", quantity=Decimal("1"), unit_price=Decimal("100.00"))
        ],
        discount_amount=Decimal("0"),
        tax_amount=Decimal("0"),
        notes=None,
        terms=None,
    )

    rows = await list_feed(db_session, organization_id=org.id)
    assert [row.event for row in rows] == ["invoice.created"]
    assert rows[0].entity_type == "invoice"
    assert rows[0].entity_id == pair.invoice.id
    assert rows[0].is_audit is False
    assert await list_audit(db_session, organization_id=org.id) == []


async def test_invoice_update_writes_no_additional_event(db_session) -> None:
    org = await make_organization(db_session)
    user = await make_user(db_session, email="invoice-noop@x.com")
    actor = await make_membership(db_session, organization=org, user=user, role=Role.OWNER)
    client = await make_client(db_session, organization=org)
    await db_session.commit()
    pair = await create_invoice(
        db_session,
        organization_id=org.id,
        actor=actor,
        client_id=client.id,
        project_id=None,
        issue_date=date(2026, 1, 1),
        due_date=date(2026, 1, 15),
        currency="USD",
        items=[
            LineItemInput(description="Work", quantity=Decimal("1"), unit_price=Decimal("100.00"))
        ],
        discount_amount=Decimal("0"),
        tax_amount=Decimal("0"),
        notes=None,
        terms=None,
    )

    await update_invoice(
        db_session,
        organization_id=org.id,
        actor=actor,
        invoice_id=pair.invoice.id,
        updates={"notes": "Revised"},
    )

    rows = await list_feed(db_session, organization_id=org.id)
    assert [row.event for row in rows] == ["invoice.created"]


async def test_send_invoice_writes_a_feed_event(db_session) -> None:
    org = await make_organization(db_session)
    user = await make_user(db_session, email="invoice-sender@x.com")
    actor = await make_membership(db_session, organization=org, user=user, role=Role.OWNER)
    client = await make_client(db_session, organization=org, email="client@x.com")
    await db_session.commit()
    pair = await create_invoice(
        db_session,
        organization_id=org.id,
        actor=actor,
        client_id=client.id,
        project_id=None,
        issue_date=date(2026, 1, 1),
        due_date=date(2026, 1, 15),
        currency="USD",
        items=[
            LineItemInput(description="Work", quantity=Decimal("1"), unit_price=Decimal("100.00"))
        ],
        discount_amount=Decimal("0"),
        tax_amount=Decimal("0"),
        notes=None,
        terms=None,
    )

    await send_invoice(db_session, organization_id=org.id, actor=actor, invoice_id=pair.invoice.id)

    rows = await list_feed(db_session, organization_id=org.id)
    assert [row.event for row in rows] == ["invoice.created", "invoice.sent"]
    assert await list_audit(db_session, organization_id=org.id) == []


async def test_cancel_invoice_writes_an_audit_event_not_feed(db_session) -> None:
    """ADR-0007: 'Cancellation is a status change with an audit event,
    never a delete.'"""
    org = await make_organization(db_session)
    user = await make_user(db_session, email="invoice-canceller@x.com")
    actor = await make_membership(db_session, organization=org, user=user, role=Role.OWNER)
    client = await make_client(db_session, organization=org)
    invoice = await make_invoice(db_session, organization=org, client=client, created_by=actor)
    await db_session.commit()

    await cancel_invoice(db_session, organization_id=org.id, actor=actor, invoice_id=invoice.id)

    audit_rows = await list_audit(db_session, organization_id=org.id)
    by_event = {row.event: row for row in audit_rows}
    assert set(by_event) == {"invoice.cancelled"}
    assert by_event["invoice.cancelled"].entity_id == invoice.id
    assert await list_feed(db_session, organization_id=org.id) == []


async def test_record_payment_writes_a_feed_event(db_session) -> None:
    org = await make_organization(db_session)
    user = await make_user(db_session, email="payment-recorder@x.com")
    actor = await make_membership(db_session, organization=org, user=user, role=Role.OWNER)
    client = await make_client(db_session, organization=org)
    invoice = await make_invoice(
        db_session,
        organization=org,
        client=client,
        created_by=actor,
        subtotal=Decimal("100.00"),
        status=InvoiceStatus.SENT,
    )
    await db_session.commit()

    payment = await record_payment(
        db_session,
        organization_id=org.id,
        actor=actor,
        invoice_id=invoice.id,
        amount=Decimal("100.00"),
        currency="USD",
        paid_on=date.today(),
        method="cash",
        reference=None,
    )

    rows = await list_feed(db_session, organization_id=org.id)
    assert [row.event for row in rows] == ["payment.recorded"]
    assert rows[0].entity_type == "payment"
    assert rows[0].entity_id == payment.id
    assert rows[0].is_audit is False
    assert await list_audit(db_session, organization_id=org.id) == []


# Phase 6 Stage 3: document_reference.created/.deleted were wired inline in
# Stage 2 (same "wire it as you build it" precedent Phase 5 Stage 9 already
# established for finance) — this is the verification pass, not new wiring.
# No `document_reference.updated` event is written at all, matching
# income/expense's own no-event-on-update precedent exactly (confirmed by
# re-reading income_service.py/expense_service.py directly before writing
# platform/documents.py's own update_document_reference).


async def test_create_document_reference_writes_a_feed_event(db_session) -> None:
    org = await make_organization(db_session)
    user = await make_user(db_session, email="document-owner@x.com")
    actor = await make_membership(db_session, organization=org, user=user, role=Role.MANAGER)
    await db_session.commit()

    document_reference = await create_document_reference(
        db_session,
        organization_id=org.id,
        actor=actor,
        title="Feed document",
        url="https://example.test",
        kind=DocumentKind.OTHER,
        project_id=None,
        client_id=None,
        meeting_id=None,
    )

    rows = await list_feed(db_session, organization_id=org.id)
    assert [row.event for row in rows] == ["document_reference.created"]
    assert rows[0].entity_type == "document_reference"
    assert rows[0].entity_id == document_reference.id
    assert rows[0].is_audit is False
    assert await list_audit(db_session, organization_id=org.id) == []


async def test_document_reference_update_writes_no_event(db_session) -> None:
    org = await make_organization(db_session)
    user = await make_user(db_session, email="document-noop@x.com")
    actor = await make_membership(db_session, organization=org, user=user, role=Role.MANAGER)
    await db_session.commit()
    document_reference = await create_document_reference(
        db_session,
        organization_id=org.id,
        actor=actor,
        title="Original",
        url="https://example.test",
        kind=DocumentKind.OTHER,
        project_id=None,
        client_id=None,
        meeting_id=None,
    )

    await update_document_reference(
        db_session,
        organization_id=org.id,
        actor=actor,
        document_reference_id=document_reference.id,
        updates={"title": "Renamed"},
    )

    # The create above already wrote one feed row — assert the update added
    # no *additional* row rather than asserting an empty feed outright.
    rows = await list_feed(db_session, organization_id=org.id)
    assert [row.event for row in rows] == ["document_reference.created"]


async def test_delete_document_reference_writes_an_audit_event_not_feed(db_session) -> None:
    """ADR-0011: document references are not one of the four soft-deleted
    entities — a hard delete, the audit event is the only remaining
    record."""
    org = await make_organization(db_session)
    user = await make_user(db_session, email="document-deleter@x.com")
    actor = await make_membership(db_session, organization=org, user=user, role=Role.MANAGER)
    await db_session.commit()
    document_reference = await create_document_reference(
        db_session,
        organization_id=org.id,
        actor=actor,
        title="To delete",
        url="https://example.test",
        kind=DocumentKind.OTHER,
        project_id=None,
        client_id=None,
        meeting_id=None,
    )
    document_reference_id = document_reference.id

    await delete_document_reference(
        db_session,
        organization_id=org.id,
        actor=actor,
        document_reference_id=document_reference_id,
    )

    audit_rows = await list_audit(db_session, organization_id=org.id)
    by_event = {row.event: row for row in audit_rows}
    assert set(by_event) == {"document_reference.deleted"}
    assert by_event["document_reference.deleted"].entity_id == document_reference_id
    feed_rows = await list_feed(db_session, organization_id=org.id)
    assert [row.event for row in feed_rows] == ["document_reference.created"]

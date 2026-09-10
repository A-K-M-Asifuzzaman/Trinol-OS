from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from trinol.core.db.org_session import OrgSession
from trinol.core.errors import ConflictError, ForbiddenError, NotFoundError
from trinol.core.ids import uuid7
from trinol.modules.identity.models import Membership
from trinol.modules.meetings.models import MeetingAction
from trinol.modules.meetings.services.meeting_service import (
    can_write_meeting,
    ensure_actor_in_org,
    ensure_meeting_visible,
    get_meeting_in_org,
)
from trinol.modules.work.models import Task, TaskPriority, TaskStatus
from trinol.modules.work.services.project_service import get_active_membership_by_user
from trinol.platform.activity import record


@dataclass(frozen=True, slots=True)
class MeetingActionList:
    items: list[MeetingAction]
    total: int


async def get_meeting_action_in_org(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    meeting_id: uuid.UUID,
    action_id: uuid.UUID,
    for_update: bool = False,
) -> MeetingAction:
    stmt = select(MeetingAction).where(
        MeetingAction.organization_id == organization_id,
        MeetingAction.meeting_id == meeting_id,
        MeetingAction.id == action_id,
    )
    if for_update:
        stmt = stmt.with_for_update()
    result = await db.execute(stmt)
    action = result.scalar_one_or_none()
    if action is None:
        raise NotFoundError("Meeting action not found")
    return action


async def list_actions(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    actor: Membership,
    meeting_id: uuid.UUID,
    limit: int = 50,
    offset: int = 0,
) -> MeetingActionList:
    ensure_actor_in_org(actor, organization_id)
    meeting = await get_meeting_in_org(db, organization_id=organization_id, meeting_id=meeting_id)
    await ensure_meeting_visible(db, meeting=meeting, actor=actor)

    total_result = await db.execute(
        select(func.count())
        .select_from(MeetingAction)
        .where(
            MeetingAction.organization_id == organization_id,
            MeetingAction.meeting_id == meeting_id,
        )
    )
    total = total_result.scalar_one()

    org_session = OrgSession(db, organization_id=organization_id)
    result = await db.execute(
        org_session.select(MeetingAction)
        .where(MeetingAction.meeting_id == meeting_id)
        .order_by(MeetingAction.created_at.asc(), MeetingAction.id.asc())
        .limit(limit)
        .offset(offset)
    )
    return MeetingActionList(items=list(result.scalars().all()), total=total)


async def create_action(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    actor: Membership,
    meeting_id: uuid.UUID,
    description: str,
    owner_id: uuid.UUID | None,
    due_date: date | None,
) -> MeetingAction:
    """Actions inherit the meeting's own edit rule (creator or MANAGER+),
    same reasoning as MeetingDecision (ROADMAP.md Phase 4 Stage 1
    decision) — no author concept, not comments' author-only rule."""
    ensure_actor_in_org(actor, organization_id)
    meeting = await get_meeting_in_org(db, organization_id=organization_id, meeting_id=meeting_id)
    if not can_write_meeting(actor, meeting):
        raise ForbiddenError("Insufficient permission to add an action item to this meeting")
    if owner_id is not None:
        await get_active_membership_by_user(db, organization_id=organization_id, user_id=owner_id)

    org_session = OrgSession(db, organization_id=organization_id)
    action = MeetingAction(
        id=uuid7(),
        meeting_id=meeting_id,
        description=description,
        owner_id=owner_id,
        due_date=due_date,
    )
    org_session.add(action)
    # Meaningful meeting content worth surfacing, same tier as
    # comment.created/meeting_decision.created.
    await record(
        db,
        organization_id=organization_id,
        event="meeting_action.created",
        entity_type="meeting_action",
        entity_id=action.id,
        actor_id=actor.user_id,
        metadata={"meeting_id": str(meeting_id)},
    )
    await db.commit()
    return action


async def update_action(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    actor: Membership,
    meeting_id: uuid.UUID,
    action_id: uuid.UUID,
    updates: dict[str, Any],
) -> MeetingAction:
    """`task_id` is never in `updates` — MeetingActionUpdateRequest doesn't
    accept it (ARCHITECTURE.md §3: it's set exactly once, by
    meetings.services.promote_action, Stage 5)."""
    ensure_actor_in_org(actor, organization_id)
    meeting = await get_meeting_in_org(db, organization_id=organization_id, meeting_id=meeting_id)
    if not can_write_meeting(actor, meeting):
        raise ForbiddenError("Insufficient permission to edit this meeting's action items")
    action = await get_meeting_action_in_org(
        db, organization_id=organization_id, meeting_id=meeting_id, action_id=action_id
    )
    if "owner_id" in updates and updates["owner_id"] is not None:
        await get_active_membership_by_user(
            db, organization_id=organization_id, user_id=updates["owner_id"]
        )

    for field, value in updates.items():
        setattr(action, field, value)
    await db.commit()
    return action


async def delete_action(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    actor: Membership,
    meeting_id: uuid.UUID,
    action_id: uuid.UUID,
) -> None:
    """ADR-0011: hard delete, recorded as an audit event — same blanket
    rule delete_decision/delete_checklist_item already follow."""
    ensure_actor_in_org(actor, organization_id)
    meeting = await get_meeting_in_org(db, organization_id=organization_id, meeting_id=meeting_id)
    if not can_write_meeting(actor, meeting):
        raise ForbiddenError("Insufficient permission to delete this meeting's action items")
    action = await get_meeting_action_in_org(
        db, organization_id=organization_id, meeting_id=meeting_id, action_id=action_id
    )

    action_id_for_event = action.id
    await record(
        db,
        organization_id=organization_id,
        event="meeting_action.deleted",
        entity_type="meeting_action",
        entity_id=action_id_for_event,
        actor_id=actor.user_id,
        metadata={"meeting_id": str(meeting_id)},
        audit=True,
    )
    await db.delete(action)
    await db.commit()


async def promote_action(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    actor: Membership,
    meeting_id: uuid.UUID,
    action_id: uuid.UUID,
) -> Task:
    """ARCHITECTURE.md §3's one documented cross-module write: one
    transaction creates the Task, stamps the action's own `task_id`, and
    records both activity events — all committed together.

    Critical: does NOT call `task_service.create_task()` — that function
    ends with its own `await db.commit()`, which would silently break the
    "one transaction" rule (an exception after would leave an orphaned
    Task with nothing to roll it back). Inlines a bare `Task(...)`
    construction instead, exactly like `lead_conversion_service.
    convert_lead` inlines `Project(...)`/`Client(...)` rather than calling
    `project_service.create_project()`.

    `for_update=True` takes a row lock on the action first (same shape and
    reason as `convert_lead`'s own lock on the lead): the second of two
    concurrent promote calls blocks until the first commits, then sees
    `task_id` already set and 409s instead of racing into a duplicate
    Task."""
    ensure_actor_in_org(actor, organization_id)
    meeting = await get_meeting_in_org(db, organization_id=organization_id, meeting_id=meeting_id)
    if not can_write_meeting(actor, meeting):
        raise ForbiddenError("Insufficient permission to promote this meeting's action items")
    action = await get_meeting_action_in_org(
        db,
        organization_id=organization_id,
        meeting_id=meeting_id,
        action_id=action_id,
        for_update=True,
    )
    if action.task_id is not None:
        raise ConflictError("This action item has already been promoted to a task")

    if action.owner_id is not None:
        await get_active_membership_by_user(
            db, organization_id=organization_id, user_id=action.owner_id
        )

    org_session = OrgSession(db, organization_id=organization_id)
    task = Task(
        id=uuid7(),
        project_id=meeting.project_id,
        title=action.description,
        assignee_id=action.owner_id,
        created_by=actor.user_id,
        milestone_id=None,
        due_date=action.due_date,
        status=TaskStatus.TODO,
        priority=TaskPriority.MEDIUM,
    )
    org_session.add(task)
    await db.flush()
    action.task_id = task.id

    # ROADMAP.md Phase 2 decision 2: ordinary feed content for both —
    # promoting is meaningful meeting content, and the resulting task
    # follows create_task's own is_audit=false precedent exactly.
    await record(
        db,
        organization_id=organization_id,
        event="meeting_action.promoted",
        entity_type="meeting_action",
        entity_id=action.id,
        actor_id=actor.user_id,
        metadata={"meeting_id": str(meeting_id), "task_id": str(task.id)},
    )
    await record(
        db,
        organization_id=organization_id,
        event="task.created",
        entity_type="task",
        entity_id=task.id,
        actor_id=actor.user_id,
        metadata={"title": task.title},
    )
    await db.commit()
    return task

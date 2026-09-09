from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from trinol.core.authz.permissions import Role
from trinol.core.db.org_session import OrgSession
from trinol.core.errors import AppError, ForbiddenError, NotFoundError
from trinol.core.ids import uuid7
from trinol.modules.identity.models import Membership
from trinol.modules.work.models import Milestone, Task, TaskAttachment, TaskPriority, TaskStatus
from trinol.modules.work.services.project_service import (
    ensure_actor_in_org,
    get_active_membership_by_user,
    get_project_in_org,
)
from trinol.platform.activity import record
from trinol.platform.file_storage.protocol import FileStorage
from trinol.platform.models import FileObject

_MANAGER_UP = (Role.MANAGER, Role.ADMIN, Role.OWNER)


@dataclass(frozen=True, slots=True)
class TaskList:
    items: list[Task]
    total: int


def can_write_task(actor: Membership, task: Task) -> bool:
    """RBAC.md §3 'Task edit' rule: MANAGER+ or the task's own assignee or
    creator. Also governs delete: RBAC.md's matrix has no dedicated
    task-delete row, and ADR-0011 treats deleting a task as a normal,
    audited action (not a hard-delete confined to managers) — so delete
    follows the same 'own tasks' control as edit rather than inventing a
    new, undocumented permission tier (ROADMAP.md Stage 3 decision)."""
    return (
        actor.role in _MANAGER_UP
        or task.assignee_id == actor.user_id
        or task.created_by == actor.user_id
    )


async def get_task_in_org(
    db: AsyncSession, *, organization_id: uuid.UUID, task_id: uuid.UUID
) -> Task:
    """Org-scoped lookup — 404s a cross-org id exactly like a missing one
    (RBAC.md §4), same pattern as get_project_in_org."""
    result = await db.execute(
        select(Task)
        .where(Task.organization_id == organization_id, Task.id == task_id)
        .execution_options(populate_existing=True)
    )
    task = result.scalar_one_or_none()
    if task is None:
        raise NotFoundError("Task not found")
    return task


async def _validate_project_and_milestone(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    project_id: uuid.UUID | None,
    milestone_id: uuid.UUID | None,
) -> None:
    if project_id is not None:
        await get_project_in_org(db, organization_id=organization_id, project_id=project_id)
    if milestone_id is not None:
        if project_id is None:
            raise AppError("milestone_id requires project_id")
        result = await db.execute(
            select(Milestone).where(
                Milestone.organization_id == organization_id, Milestone.id == milestone_id
            )
        )
        milestone = result.scalar_one_or_none()
        if milestone is None:
            raise AppError("milestone_id must reference an existing milestone")
        if milestone.project_id != project_id:
            raise AppError("milestone_id must belong to the same project")


def _completed_at_for_status(status: TaskStatus) -> datetime | None:
    """Derived from status, never client-settable (schemas.py) — one
    source of truth for ck_task_completed instead of trusting a client-sent
    date to agree with the status sent alongside it."""
    return datetime.now(UTC) if status == TaskStatus.DONE else None


async def create_task(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    actor: Membership,
    project_id: uuid.UUID | None,
    title: str,
    description: str | None,
    status: TaskStatus,
    priority: TaskPriority,
    assignee_id: uuid.UUID | None,
    milestone_id: uuid.UUID | None,
    due_date: date | None,
    start_date: date | None,
    estimated_hours: Decimal | None,
    actual_hours: Decimal | None,
    tags: list[str] | None,
) -> Task:
    ensure_actor_in_org(actor, organization_id)
    # RBAC.md §2: "Create/edit own tasks" is granted to every role — no
    # ownership check on create, there's no prior resource to own yet.
    # created_by is always the actor, never client-settable (schemas.py).
    await _validate_project_and_milestone(
        db, organization_id=organization_id, project_id=project_id, milestone_id=milestone_id
    )
    if assignee_id is not None:
        await get_active_membership_by_user(
            db, organization_id=organization_id, user_id=assignee_id
        )

    org_session = OrgSession(db, organization_id=organization_id)
    task = Task(
        id=uuid7(),
        project_id=project_id,
        title=title,
        description=description,
        status=status,
        priority=priority,
        assignee_id=assignee_id,
        created_by=actor.user_id,
        milestone_id=milestone_id,
        due_date=due_date,
        start_date=start_date,
        estimated_hours=estimated_hours,
        actual_hours=actual_hours,
        tags=tags,
        completed_at=_completed_at_for_status(status),
    )
    org_session.add(task)
    # ROADMAP.md Phase 2 decision 2: ordinary feed content, is_audit=false.
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


async def list_tasks(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    actor: Membership,
    project_id: uuid.UUID | None = None,
    assignee_id: uuid.UUID | None = None,
    status: TaskStatus | None = None,
    limit: int = 50,
    offset: int = 0,
) -> TaskList:
    """RBAC.md §2 grants TASK_READ org-wide to every role; unlike "Project
    detail", §3 documents no additional per-resource read restriction for
    tasks — read is org-wide transparency here, same as Team's own "view"
    row; only editing is ownership-restricted. Flagged as a ROADMAP.md
    Stage 3 decision since the asymmetry with projects isn't spelled out
    explicitly in RBAC.md and is worth an explicit second look."""
    ensure_actor_in_org(actor, organization_id)

    filters: list[Any] = []
    if project_id is not None:
        filters.append(Task.project_id == project_id)
    if assignee_id is not None:
        filters.append(Task.assignee_id == assignee_id)
    if status is not None:
        filters.append(Task.status == status)

    total_result = await db.execute(
        select(func.count())
        .select_from(Task)
        .where(Task.organization_id == organization_id, *filters)
    )
    total = total_result.scalar_one()

    org_session = OrgSession(db, organization_id=organization_id)
    result = await db.execute(
        org_session.select(Task)
        .where(*filters)
        .order_by(Task.created_at.desc(), Task.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return TaskList(items=list(result.scalars().all()), total=total)


async def get_task(
    db: AsyncSession, *, organization_id: uuid.UUID, actor: Membership, task_id: uuid.UUID
) -> Task:
    ensure_actor_in_org(actor, organization_id)
    return await get_task_in_org(db, organization_id=organization_id, task_id=task_id)


async def update_task(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    actor: Membership,
    task_id: uuid.UUID,
    updates: dict[str, Any],
) -> Task:
    ensure_actor_in_org(actor, organization_id)
    task = await get_task_in_org(db, organization_id=organization_id, task_id=task_id)
    if not can_write_task(actor, task):
        raise ForbiddenError("Insufficient permission to edit this task")

    if "project_id" in updates or "milestone_id" in updates:
        resolved_project_id = updates.get("project_id", task.project_id)
        resolved_milestone_id = updates.get("milestone_id", task.milestone_id)
        await _validate_project_and_milestone(
            db,
            organization_id=organization_id,
            project_id=resolved_project_id,
            milestone_id=resolved_milestone_id,
        )
    if "assignee_id" in updates and updates["assignee_id"] is not None:
        await get_active_membership_by_user(
            db, organization_id=organization_id, user_id=updates["assignee_id"]
        )

    previous_status = task.status
    for field, value in updates.items():
        setattr(task, field, value)
    if "status" in updates:
        task.completed_at = _completed_at_for_status(updates["status"])

    if "status" in updates and task.status != previous_status:
        # ROADMAP.md Phase 2 decision 2: a transition *to* DONE is its own
        # named event (task.completed), not also a generic status_changed
        # — the two are distinct entries in the approved event list, not
        # one general "field changed" event with different metadata.
        if task.status == TaskStatus.DONE:
            await record(
                db,
                organization_id=organization_id,
                event="task.completed",
                entity_type="task",
                entity_id=task.id,
                actor_id=actor.user_id,
                metadata={"from": previous_status.value},
            )
        else:
            await record(
                db,
                organization_id=organization_id,
                event="task.status_changed",
                entity_type="task",
                entity_id=task.id,
                actor_id=actor.user_id,
                metadata={"from": previous_status.value, "to": task.status.value},
            )

    await db.commit()
    return await get_task_in_org(db, organization_id=organization_id, task_id=task_id)


async def delete_task(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    actor: Membership,
    task_id: uuid.UUID,
    storage: FileStorage,
) -> None:
    """ADR-0011: tasks are hard-deleted, cascading to comments/checklist
    items (Stage 1's CASCADE FKs). "The audit event keeps the record of
    who did it and when" — the row is gone after this, so the event is the
    only remaining record; it must be written in the same transaction, not
    deferred to Stage 7's ordinary feed-event wiring.

    ADR-0008: "deleting a database row must also delete the object."
    `task_attachments` cascades away at the DB level, but `file_objects`
    doesn't hang off `tasks` in the FK graph at all, so its rows (and the
    blobs they name) would otherwise be silently orphaned on every task
    delete that had attachments — not a rare edge case, the *only* path by
    which this could happen. Deleted explicitly here, in the order the FK
    constraints require: `task_attachments` (references both `tasks` and
    `file_objects`) before `file_objects`, all before the `task` itself —
    `file_objects.file_id`'s `RESTRICT` would otherwise reject deleting a
    still-referenced row."""
    ensure_actor_in_org(actor, organization_id)
    task = await get_task_in_org(db, organization_id=organization_id, task_id=task_id)
    if not can_write_task(actor, task):
        raise ForbiddenError("Insufficient permission to delete this task")

    attachments_result = await db.execute(
        select(TaskAttachment).where(
            TaskAttachment.organization_id == organization_id, TaskAttachment.task_id == task_id
        )
    )
    attachments = list(attachments_result.scalars().all())
    file_objects: list[FileObject] = []
    if attachments:
        file_objects_result = await db.execute(
            select(FileObject).where(
                FileObject.organization_id == organization_id,
                FileObject.id.in_([a.file_id for a in attachments]),
            )
        )
        file_objects = list(file_objects_result.scalars().all())

    task_id_for_event = task.id
    await record(
        db,
        organization_id=organization_id,
        event="task.deleted",
        entity_type="task",
        entity_id=task_id_for_event,
        actor_id=actor.user_id,
        metadata={"title": task.title},
        audit=True,
    )

    for attachment in attachments:
        await db.delete(attachment)
    await db.flush()
    for file_object in file_objects:
        await db.delete(file_object)
    await db.delete(task)
    await db.commit()

    for file_object in file_objects:
        await storage.delete(file_object.storage_key)

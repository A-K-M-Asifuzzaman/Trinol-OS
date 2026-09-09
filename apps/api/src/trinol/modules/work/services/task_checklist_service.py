from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from trinol.core.db.org_session import OrgSession
from trinol.core.errors import ForbiddenError, NotFoundError
from trinol.core.ids import uuid7
from trinol.modules.identity.models import Membership
from trinol.modules.work.models import Task, TaskChecklistItem
from trinol.modules.work.services.project_service import ensure_actor_in_org
from trinol.modules.work.services.task_service import can_write_task, get_task_in_org
from trinol.platform.activity import record


@dataclass(frozen=True, slots=True)
class TaskChecklistItemList:
    items: list[TaskChecklistItem]
    total: int


def _ensure_can_write_checklist(actor: Membership, task: Task) -> None:
    """Checklist items are task content, not independent discourse like
    comments — there's no author concept to hang a separate rule on, so
    they follow the same rule as editing the task itself (ROADMAP.md
    Stage 5 decision), not comments' author-only rule."""
    if not can_write_task(actor, task):
        raise ForbiddenError("Insufficient permission to edit this task's checklist")


async def get_checklist_item_in_org(
    db: AsyncSession, *, organization_id: uuid.UUID, task_id: uuid.UUID, item_id: uuid.UUID
) -> TaskChecklistItem:
    result = await db.execute(
        select(TaskChecklistItem).where(
            TaskChecklistItem.organization_id == organization_id,
            TaskChecklistItem.task_id == task_id,
            TaskChecklistItem.id == item_id,
        )
    )
    item = result.scalar_one_or_none()
    if item is None:
        raise NotFoundError("Checklist item not found")
    return item


async def create_checklist_item(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    actor: Membership,
    task_id: uuid.UUID,
    label: str,
    position: int,
) -> TaskChecklistItem:
    ensure_actor_in_org(actor, organization_id)
    task = await get_task_in_org(db, organization_id=organization_id, task_id=task_id)
    _ensure_can_write_checklist(actor, task)

    org_session = OrgSession(db, organization_id=organization_id)
    item = TaskChecklistItem(id=uuid7(), task_id=task_id, label=label, position=position)
    org_session.add(item)
    await db.commit()
    return item


async def list_checklist_items(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    actor: Membership,
    task_id: uuid.UUID,
    limit: int = 50,
    offset: int = 0,
) -> TaskChecklistItemList:
    ensure_actor_in_org(actor, organization_id)
    await get_task_in_org(db, organization_id=organization_id, task_id=task_id)

    total_result = await db.execute(
        select(func.count())
        .select_from(TaskChecklistItem)
        .where(
            TaskChecklistItem.organization_id == organization_id,
            TaskChecklistItem.task_id == task_id,
        )
    )
    total = total_result.scalar_one()

    org_session = OrgSession(db, organization_id=organization_id)
    result = await db.execute(
        org_session.select(TaskChecklistItem)
        .where(TaskChecklistItem.task_id == task_id)
        .order_by(TaskChecklistItem.position.asc(), TaskChecklistItem.id.asc())
        .limit(limit)
        .offset(offset)
    )
    return TaskChecklistItemList(items=list(result.scalars().all()), total=total)


async def update_checklist_item(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    actor: Membership,
    task_id: uuid.UUID,
    item_id: uuid.UUID,
    updates: dict[str, Any],
) -> TaskChecklistItem:
    ensure_actor_in_org(actor, organization_id)
    task = await get_task_in_org(db, organization_id=organization_id, task_id=task_id)
    _ensure_can_write_checklist(actor, task)
    item = await get_checklist_item_in_org(
        db, organization_id=organization_id, task_id=task_id, item_id=item_id
    )
    for field, value in updates.items():
        setattr(item, field, value)
    await db.commit()
    return item


async def delete_checklist_item(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    actor: Membership,
    task_id: uuid.UUID,
    item_id: uuid.UUID,
) -> None:
    """ADR-0011 names checklist items explicitly alongside tasks and
    comments for the audit-on-delete requirement — same reasoning as
    delete_task/delete_comment: the row is gone afterward."""
    ensure_actor_in_org(actor, organization_id)
    task = await get_task_in_org(db, organization_id=organization_id, task_id=task_id)
    _ensure_can_write_checklist(actor, task)
    item = await get_checklist_item_in_org(
        db, organization_id=organization_id, task_id=task_id, item_id=item_id
    )

    item_id_for_event = item.id
    await record(
        db,
        organization_id=organization_id,
        event="task_checklist_item.deleted",
        entity_type="task_checklist_item",
        entity_id=item_id_for_event,
        actor_id=actor.user_id,
        metadata={"task_id": str(task_id), "label": item.label},
        audit=True,
    )
    await db.delete(item)
    await db.commit()

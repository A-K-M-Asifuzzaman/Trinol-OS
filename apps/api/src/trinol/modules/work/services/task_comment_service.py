from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from trinol.core.authz.permissions import Role
from trinol.core.db.org_session import OrgSession
from trinol.core.errors import ForbiddenError, NotFoundError
from trinol.core.ids import uuid7
from trinol.modules.identity.models import Membership
from trinol.modules.work.models import TaskComment
from trinol.modules.work.services.project_service import ensure_actor_in_org
from trinol.modules.work.services.task_service import get_task_in_org
from trinol.platform.activity import record

_ADMIN_UP = (Role.ADMIN, Role.OWNER)


@dataclass(frozen=True, slots=True)
class TaskCommentList:
    items: list[TaskComment]
    total: int


async def get_comment_in_org(
    db: AsyncSession, *, organization_id: uuid.UUID, task_id: uuid.UUID, comment_id: uuid.UUID
) -> TaskComment:
    result = await db.execute(
        select(TaskComment)
        .where(
            TaskComment.organization_id == organization_id,
            TaskComment.task_id == task_id,
            TaskComment.id == comment_id,
        )
        .execution_options(populate_existing=True)
    )
    comment = result.scalar_one_or_none()
    if comment is None:
        raise NotFoundError("Comment not found")
    return comment


async def create_comment(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    actor: Membership,
    task_id: uuid.UUID,
    body: str,
) -> TaskComment:
    """RBAC.md §3 documents no restriction on who may comment — any org
    member who can see the task (org-wide, Stage 3 decision) may add one,
    same as task creation's own 'everyone' rule (ROADMAP.md Stage 5
    decision)."""
    ensure_actor_in_org(actor, organization_id)
    await get_task_in_org(db, organization_id=organization_id, task_id=task_id)

    org_session = OrgSession(db, organization_id=organization_id)
    comment = TaskComment(id=uuid7(), task_id=task_id, author_id=actor.user_id, body=body)
    org_session.add(comment)
    # ROADMAP.md Phase 2 decision 2: ordinary feed content, is_audit=false.
    await record(
        db,
        organization_id=organization_id,
        event="comment.created",
        entity_type="task_comment",
        entity_id=comment.id,
        actor_id=actor.user_id,
        metadata={"task_id": str(task_id)},
    )
    await db.commit()
    return comment


async def list_comments(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    actor: Membership,
    task_id: uuid.UUID,
    limit: int = 50,
    offset: int = 0,
) -> TaskCommentList:
    ensure_actor_in_org(actor, organization_id)
    await get_task_in_org(db, organization_id=organization_id, task_id=task_id)

    total_result = await db.execute(
        select(func.count())
        .select_from(TaskComment)
        .where(TaskComment.organization_id == organization_id, TaskComment.task_id == task_id)
    )
    total = total_result.scalar_one()

    org_session = OrgSession(db, organization_id=organization_id)
    result = await db.execute(
        org_session.select(TaskComment)
        .where(TaskComment.task_id == task_id)
        .order_by(TaskComment.created_at.asc(), TaskComment.id.asc())
        .limit(limit)
        .offset(offset)
    )
    return TaskCommentList(items=list(result.scalars().all()), total=total)


async def update_comment(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    actor: Membership,
    task_id: uuid.UUID,
    comment_id: uuid.UUID,
    body: str,
) -> TaskComment:
    """RBAC.md §3: "Comment edit/delete: author only" — edit has no
    ADMIN+ override, unlike delete below."""
    ensure_actor_in_org(actor, organization_id)
    await get_task_in_org(db, organization_id=organization_id, task_id=task_id)
    comment = await get_comment_in_org(
        db, organization_id=organization_id, task_id=task_id, comment_id=comment_id
    )
    if comment.author_id != actor.user_id:
        raise ForbiddenError("Only the author may edit this comment")

    comment.body = body
    comment.edited_at = datetime.now(UTC)
    await db.commit()
    return await get_comment_in_org(
        db, organization_id=organization_id, task_id=task_id, comment_id=comment_id
    )


async def delete_comment(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    actor: Membership,
    task_id: uuid.UUID,
    comment_id: uuid.UUID,
) -> None:
    """RBAC.md §3: "(ADMIN+ may delete)" — the one place author-only
    doesn't fully apply. ADR-0011 names comments explicitly alongside
    tasks for the audit-on-delete requirement: the row is gone afterward,
    so the event is the only remaining record."""
    ensure_actor_in_org(actor, organization_id)
    await get_task_in_org(db, organization_id=organization_id, task_id=task_id)
    comment = await get_comment_in_org(
        db, organization_id=organization_id, task_id=task_id, comment_id=comment_id
    )
    if comment.author_id != actor.user_id and actor.role not in _ADMIN_UP:
        raise ForbiddenError("Only the author or an ADMIN+ may delete this comment")

    comment_id_for_event = comment.id
    await record(
        db,
        organization_id=organization_id,
        event="task_comment.deleted",
        entity_type="task_comment",
        entity_id=comment_id_for_event,
        actor_id=actor.user_id,
        metadata={"task_id": str(task_id)},
        audit=True,
    )
    await db.delete(comment)
    await db.commit()

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from trinol.core.db.org_session import OrgSession
from trinol.core.errors import ForbiddenError, NotFoundError
from trinol.core.ids import uuid7
from trinol.modules.identity.models import Membership
from trinol.modules.work.models import TaskAttachment
from trinol.modules.work.services.project_service import ensure_actor_in_org
from trinol.modules.work.services.task_service import can_write_task, get_task_in_org
from trinol.platform.activity import record
from trinol.platform.file_storage.protocol import FileStorage
from trinol.platform.files import create_file_object
from trinol.platform.models import FileObject


@dataclass(frozen=True, slots=True)
class AttachmentWithFile:
    """`TaskAttachmentResponse`'s fields (filename/content_type/size_bytes)
    live on `FileObject`, not `TaskAttachment` — this pairs the two, same
    pattern as identity's `TeamMember` (Membership+User)."""

    attachment: TaskAttachment
    file_object: FileObject


@dataclass(frozen=True, slots=True)
class TaskAttachmentList:
    items: list[AttachmentWithFile]
    total: int


@dataclass(frozen=True, slots=True)
class AttachmentDownload:
    file_object: FileObject
    data: bytes


async def get_attachment_in_org(
    db: AsyncSession, *, organization_id: uuid.UUID, task_id: uuid.UUID, attachment_id: uuid.UUID
) -> TaskAttachment:
    result = await db.execute(
        select(TaskAttachment).where(
            TaskAttachment.organization_id == organization_id,
            TaskAttachment.task_id == task_id,
            TaskAttachment.id == attachment_id,
        )
    )
    attachment = result.scalar_one_or_none()
    if attachment is None:
        raise NotFoundError("Attachment not found")
    return attachment


async def _get_file_object_in_org(
    db: AsyncSession, *, organization_id: uuid.UUID, file_id: uuid.UUID
) -> FileObject:
    result = await db.execute(
        select(FileObject).where(
            FileObject.organization_id == organization_id, FileObject.id == file_id
        )
    )
    file_object = result.scalar_one_or_none()
    if file_object is None:
        raise NotFoundError("File not found")
    return file_object


async def create_attachment(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    actor: Membership,
    task_id: uuid.UUID,
    filename: str,
    data: bytes,
    storage: FileStorage,
) -> AttachmentWithFile:
    """Attachments are task content, not independent discourse — same rule
    as checklist items (`can_write_task`), not comments' author-only rule
    (ROADMAP.md Stage 6 decision, extending Stage 5's reasoning: there's no
    author concept here either)."""
    ensure_actor_in_org(actor, organization_id)
    task = await get_task_in_org(db, organization_id=organization_id, task_id=task_id)
    if not can_write_task(actor, task):
        raise ForbiddenError("Insufficient permission to attach files to this task")

    file_object = await create_file_object(
        db,
        organization_id=organization_id,
        uploaded_by=actor.user_id,
        filename=filename,
        data=data,
        storage=storage,
    )

    org_session = OrgSession(db, organization_id=organization_id)
    attachment = TaskAttachment(
        id=uuid7(), task_id=task_id, file_id=file_object.id, uploaded_by=actor.user_id
    )
    org_session.add(attachment)
    await db.commit()
    return AttachmentWithFile(attachment=attachment, file_object=file_object)


async def list_attachments(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    actor: Membership,
    task_id: uuid.UUID,
    limit: int = 50,
    offset: int = 0,
) -> TaskAttachmentList:
    ensure_actor_in_org(actor, organization_id)
    await get_task_in_org(db, organization_id=organization_id, task_id=task_id)

    total_result = await db.execute(
        select(func.count())
        .select_from(TaskAttachment)
        .where(TaskAttachment.organization_id == organization_id, TaskAttachment.task_id == task_id)
    )
    total = total_result.scalar_one()

    org_session = OrgSession(db, organization_id=organization_id)
    result = await db.execute(
        org_session.select(TaskAttachment)
        .where(TaskAttachment.task_id == task_id)
        .order_by(TaskAttachment.created_at.asc(), TaskAttachment.id.asc())
        .limit(limit)
        .offset(offset)
    )
    attachments = list(result.scalars().all())

    file_objects_result = await db.execute(
        select(FileObject).where(
            FileObject.organization_id == organization_id,
            FileObject.id.in_([a.file_id for a in attachments]),
        )
    )
    file_objects_by_id = {fo.id: fo for fo in file_objects_result.scalars().all()}
    items = [
        AttachmentWithFile(attachment=a, file_object=file_objects_by_id[a.file_id])
        for a in attachments
    ]
    return TaskAttachmentList(items=items, total=total)


async def download_attachment(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    actor: Membership,
    task_id: uuid.UUID,
    attachment_id: uuid.UUID,
    storage: FileStorage,
) -> AttachmentDownload:
    """Authorized by the parent task's own read rule, no separate
    attachment-level permission (ADR-0008, ROADMAP.md Stage 6 decision) —
    task read is org-wide (Stage 3), so any org member who can see the
    task can download its attachments."""
    ensure_actor_in_org(actor, organization_id)
    await get_task_in_org(db, organization_id=organization_id, task_id=task_id)
    attachment = await get_attachment_in_org(
        db, organization_id=organization_id, task_id=task_id, attachment_id=attachment_id
    )
    file_object = await _get_file_object_in_org(
        db, organization_id=organization_id, file_id=attachment.file_id
    )
    data = await storage.get(file_object.storage_key)
    return AttachmentDownload(file_object=file_object, data=data)


async def delete_attachment(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    actor: Membership,
    task_id: uuid.UUID,
    attachment_id: uuid.UUID,
    storage: FileStorage,
) -> None:
    """ADR-0011's audit-on-delete list names task/comment/checklist item
    specifically but not attachments — the same reasoning applies
    identically (hard delete, row gone after), so this extends the
    pattern proactively (ROADMAP.md Stage 6 decision) rather than leaving
    the same category of gap two prior review rounds already caught.

    ADR-0008: "deleting a database row must also delete the object" — the
    `file_objects` row and the blob are deleted here too, in that order
    (DB commit first, then the blob), so a failure after the commit
    orphans a blob (the documented backstop) rather than leaving a
    dangling DB reference to an already-deleted blob."""
    ensure_actor_in_org(actor, organization_id)
    task = await get_task_in_org(db, organization_id=organization_id, task_id=task_id)
    if not can_write_task(actor, task):
        raise ForbiddenError("Insufficient permission to delete this attachment")
    attachment = await get_attachment_in_org(
        db, organization_id=organization_id, task_id=task_id, attachment_id=attachment_id
    )
    file_object = await _get_file_object_in_org(
        db, organization_id=organization_id, file_id=attachment.file_id
    )

    attachment_id_for_event = attachment.id
    storage_key = file_object.storage_key
    await record(
        db,
        organization_id=organization_id,
        event="task_attachment.deleted",
        entity_type="task_attachment",
        entity_id=attachment_id_for_event,
        actor_id=actor.user_id,
        metadata={"task_id": str(task_id), "filename": file_object.filename},
        audit=True,
    )
    await db.delete(attachment)
    await db.flush()
    await db.delete(file_object)
    await db.commit()
    await storage.delete(storage_key)

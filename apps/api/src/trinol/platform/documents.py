from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from trinol.core.db.org_session import OrgSession
from trinol.core.errors import ForbiddenError, NotFoundError
from trinol.core.ids import uuid7
from trinol.modules.crm.services.client_service import get_client_in_org
from trinol.modules.identity.models import Membership
from trinol.modules.meetings.services.meeting_service import get_meeting_in_org
from trinol.modules.work.services.project_service import get_project_in_org
from trinol.platform.activity import record
from trinol.platform.models import DocumentKind, DocumentReference

# Phase 6 plan decision 3: no ownership-split anywhere in this module —
# DOCUMENT_READ/DOCUMENT_WRITE (route-level `require(...)`) are the entire
# authorization check, same shape as finance's income_service.py.


@dataclass(frozen=True, slots=True)
class DocumentReferenceList:
    items: list[DocumentReference]
    total: int


def ensure_actor_in_org(actor: Membership, organization_id: uuid.UUID) -> None:
    """Defense in depth, same reasoning as every other module's own copy of
    this check (e.g. finance.services.income_service.ensure_actor_in_org)."""
    if actor.organization_id != organization_id:
        raise ForbiddenError("Actor does not belong to this organization")


async def _validate_references(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    project_id: uuid.UUID | None,
    client_id: uuid.UUID | None,
    meeting_id: uuid.UUID | None,
) -> None:
    """A reference may have zero, one, or more than one parent set
    (Phase 6 plan decision 4) — each one present is independently
    validated to exist in this org, same reasoning as income_service's own
    `_validate_references`. No additional visibility check beyond
    existence (decision 3)."""
    if project_id is not None:
        await get_project_in_org(db, organization_id=organization_id, project_id=project_id)
    if client_id is not None:
        await get_client_in_org(db, organization_id=organization_id, client_id=client_id)
    if meeting_id is not None:
        await get_meeting_in_org(db, organization_id=organization_id, meeting_id=meeting_id)


async def get_document_reference_in_org(
    db: AsyncSession, *, organization_id: uuid.UUID, document_reference_id: uuid.UUID
) -> DocumentReference:
    """Org-scoped lookup — 404s a cross-org id exactly like a missing one
    (RBAC.md §4), same pattern as get_income_in_org/get_client_in_org."""
    result = await db.execute(
        select(DocumentReference)
        .where(
            DocumentReference.organization_id == organization_id,
            DocumentReference.id == document_reference_id,
        )
        .execution_options(populate_existing=True)
    )
    document_reference = result.scalar_one_or_none()
    if document_reference is None:
        raise NotFoundError("Document reference not found")
    return document_reference


async def create_document_reference(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    actor: Membership,
    title: str,
    url: str,
    kind: DocumentKind,
    project_id: uuid.UUID | None,
    client_id: uuid.UUID | None,
    meeting_id: uuid.UUID | None,
) -> DocumentReference:
    ensure_actor_in_org(actor, organization_id)
    await _validate_references(
        db,
        organization_id=organization_id,
        project_id=project_id,
        client_id=client_id,
        meeting_id=meeting_id,
    )

    org_session = OrgSession(db, organization_id=organization_id)
    document_reference = DocumentReference(
        id=uuid7(),
        title=title,
        url=url,
        kind=kind,
        project_id=project_id,
        client_id=client_id,
        meeting_id=meeting_id,
        added_by=actor.user_id,
    )
    org_session.add(document_reference)
    await record(
        db,
        organization_id=organization_id,
        event="document_reference.created",
        entity_type="document_reference",
        entity_id=document_reference.id,
        actor_id=actor.user_id,
        metadata={"title": document_reference.title},
    )
    await db.commit()
    return document_reference


async def list_document_references(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    actor: Membership,
    project_id: uuid.UUID | None = None,
    client_id: uuid.UUID | None = None,
    meeting_id: uuid.UUID | None = None,
    limit: int = 50,
    offset: int = 0,
) -> DocumentReferenceList:
    """Optional `project_id`/`client_id`/`meeting_id` filters — cheap to
    add now and reusable later even though no frontend page uses them this
    stage (Phase 6 plan Stage 2)."""
    ensure_actor_in_org(actor, organization_id)

    extra_filters = []
    if project_id is not None:
        extra_filters.append(DocumentReference.project_id == project_id)
    if client_id is not None:
        extra_filters.append(DocumentReference.client_id == client_id)
    if meeting_id is not None:
        extra_filters.append(DocumentReference.meeting_id == meeting_id)

    total_result = await db.execute(
        select(func.count())
        .select_from(DocumentReference)
        .where(DocumentReference.organization_id == organization_id, *extra_filters)
    )
    total = total_result.scalar_one()

    org_session = OrgSession(db, organization_id=organization_id)
    result = await db.execute(
        org_session.select(DocumentReference)
        .where(*extra_filters)
        .order_by(DocumentReference.created_at.desc(), DocumentReference.id.asc())
        .limit(limit)
        .offset(offset)
    )
    return DocumentReferenceList(items=list(result.scalars().all()), total=total)


async def get_document_reference(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    actor: Membership,
    document_reference_id: uuid.UUID,
) -> DocumentReference:
    ensure_actor_in_org(actor, organization_id)
    return await get_document_reference_in_org(
        db, organization_id=organization_id, document_reference_id=document_reference_id
    )


async def update_document_reference(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    actor: Membership,
    document_reference_id: uuid.UUID,
    updates: dict[str, Any],
) -> DocumentReference:
    ensure_actor_in_org(actor, organization_id)
    document_reference = await get_document_reference_in_org(
        db, organization_id=organization_id, document_reference_id=document_reference_id
    )

    await _validate_references(
        db,
        organization_id=organization_id,
        project_id=updates.get("project_id", document_reference.project_id),
        client_id=updates.get("client_id", document_reference.client_id),
        meeting_id=updates.get("meeting_id", document_reference.meeting_id),
    )

    for field, value in updates.items():
        setattr(document_reference, field, value)

    # No activity event on update — matches income_service.update_income/
    # expense_service.update_expense's own precedent exactly (only create
    # and delete are recorded for these simple-field-edit entities).
    await db.commit()
    return await get_document_reference_in_org(
        db, organization_id=organization_id, document_reference_id=document_reference_id
    )


async def delete_document_reference(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    actor: Membership,
    document_reference_id: uuid.UUID,
) -> None:
    """ADR-0011: not one of the four soft-deleted entities — a hard
    delete, with the deletion recorded as an audit event (same reasoning
    as income_service.delete_income)."""
    ensure_actor_in_org(actor, organization_id)
    document_reference = await get_document_reference_in_org(
        db, organization_id=organization_id, document_reference_id=document_reference_id
    )

    await record(
        db,
        organization_id=organization_id,
        event="document_reference.deleted",
        entity_type="document_reference",
        entity_id=document_reference.id,
        actor_id=actor.user_id,
        metadata={"title": document_reference.title},
        audit=True,
    )
    await db.delete(document_reference)
    await db.commit()

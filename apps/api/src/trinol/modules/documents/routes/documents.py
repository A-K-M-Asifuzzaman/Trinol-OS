from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from trinol.core.authz.permissions import Permission
from trinol.core.authz.require import require
from trinol.core.db.engine import get_db_session
from trinol.modules.documents.models import DocumentReference
from trinol.modules.documents.schemas import (
    DocumentReferenceCreateRequest,
    DocumentReferenceListResponse,
    DocumentReferenceResponse,
    DocumentReferenceUpdateRequest,
)
from trinol.modules.documents.services.document_service import (
    create_document_reference,
    delete_document_reference,
    get_document_reference,
    list_document_references,
    update_document_reference,
)
from trinol.modules.identity.deps import get_current_membership
from trinol.modules.identity.models import Membership

router = APIRouter(prefix="/api/v1/documents", tags=["documents"])


def _document_reference_to_response(
    document_reference: DocumentReference,
) -> DocumentReferenceResponse:
    return DocumentReferenceResponse(
        id=document_reference.id,
        title=document_reference.title,
        url=document_reference.url,
        kind=document_reference.kind,
        project_id=document_reference.project_id,
        client_id=document_reference.client_id,
        meeting_id=document_reference.meeting_id,
        added_by=document_reference.added_by,
        created_at=document_reference.created_at,
        updated_at=document_reference.updated_at,
    )


@router.post(
    "",
    response_model=DocumentReferenceResponse,
    status_code=201,
    dependencies=[Depends(require(Permission.DOCUMENT_WRITE))],
)
async def create_document_reference_route(
    payload: DocumentReferenceCreateRequest,
    membership: Membership = Depends(get_current_membership),
    db: AsyncSession = Depends(get_db_session),
) -> DocumentReferenceResponse:
    document_reference = await create_document_reference(
        db,
        organization_id=membership.organization_id,
        actor=membership,
        title=payload.title,
        url=payload.url,
        kind=payload.kind,
        project_id=payload.project_id,
        client_id=payload.client_id,
        meeting_id=payload.meeting_id,
    )
    return _document_reference_to_response(document_reference)


@router.get(
    "",
    response_model=DocumentReferenceListResponse,
    dependencies=[Depends(require(Permission.DOCUMENT_READ))],
)
async def list_document_references_route(
    project_id: uuid.UUID | None = None,
    client_id: uuid.UUID | None = None,
    meeting_id: uuid.UUID | None = None,
    limit: int = Query(default=50, ge=1, le=200),  # ADR-0005: default 50, hard cap 200
    offset: int = Query(default=0, ge=0),
    membership: Membership = Depends(get_current_membership),
    db: AsyncSession = Depends(get_db_session),
) -> DocumentReferenceListResponse:
    result = await list_document_references(
        db,
        organization_id=membership.organization_id,
        actor=membership,
        project_id=project_id,
        client_id=client_id,
        meeting_id=meeting_id,
        limit=limit,
        offset=offset,
    )
    return DocumentReferenceListResponse(
        items=[_document_reference_to_response(d) for d in result.items], total=result.total
    )


@router.get(
    "/{document_reference_id}",
    response_model=DocumentReferenceResponse,
    dependencies=[Depends(require(Permission.DOCUMENT_READ))],
)
async def get_document_reference_route(
    document_reference_id: uuid.UUID,
    membership: Membership = Depends(get_current_membership),
    db: AsyncSession = Depends(get_db_session),
) -> DocumentReferenceResponse:
    document_reference = await get_document_reference(
        db,
        organization_id=membership.organization_id,
        actor=membership,
        document_reference_id=document_reference_id,
    )
    return _document_reference_to_response(document_reference)


@router.patch(
    "/{document_reference_id}",
    response_model=DocumentReferenceResponse,
    dependencies=[Depends(require(Permission.DOCUMENT_WRITE))],
)
async def update_document_reference_route(
    document_reference_id: uuid.UUID,
    payload: DocumentReferenceUpdateRequest,
    membership: Membership = Depends(get_current_membership),
    db: AsyncSession = Depends(get_db_session),
) -> DocumentReferenceResponse:
    updates = payload.model_dump(exclude_unset=True)
    document_reference = await update_document_reference(
        db,
        organization_id=membership.organization_id,
        actor=membership,
        document_reference_id=document_reference_id,
        updates=updates,
    )
    return _document_reference_to_response(document_reference)


@router.delete(
    "/{document_reference_id}",
    status_code=204,
    dependencies=[Depends(require(Permission.DOCUMENT_WRITE))],
)
async def delete_document_reference_route(
    document_reference_id: uuid.UUID,
    membership: Membership = Depends(get_current_membership),
    db: AsyncSession = Depends(get_db_session),
) -> None:
    await delete_document_reference(
        db,
        organization_id=membership.organization_id,
        actor=membership,
        document_reference_id=document_reference_id,
    )

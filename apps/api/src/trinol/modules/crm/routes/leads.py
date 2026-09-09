from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from trinol.core.authz.permissions import Permission
from trinol.core.authz.require import require
from trinol.core.db.engine import get_db_session
from trinol.modules.crm.models import Lead, LeadStage
from trinol.modules.crm.schemas import (
    LeadCreateRequest,
    LeadListResponse,
    LeadResponse,
    LeadStatsResponse,
    LeadUpdateRequest,
)
from trinol.modules.crm.services.lead_service import (
    archive_lead,
    create_lead,
    get_lead,
    get_lead_stats,
    list_leads,
    update_lead,
)
from trinol.modules.identity.deps import get_current_membership
from trinol.modules.identity.models import Membership

router = APIRouter(prefix="/api/v1/leads", tags=["crm"])


def lead_to_response(lead: Lead) -> LeadResponse:
    return LeadResponse(
        id=lead.id,
        name=lead.name,
        company=lead.company,
        email=lead.email,
        phone=lead.phone,
        source=lead.source,
        service=lead.service,
        estimated_value=lead.estimated_value,
        currency=lead.currency,
        stage=lead.stage,
        assigned_to=lead.assigned_to,
        next_follow_up=lead.next_follow_up,
        notes=lead.notes,
        converted_client_id=lead.converted_client_id,
        converted_at=lead.converted_at,
        lost_reason=lead.lost_reason,
        board_position=lead.board_position,
        archived_at=lead.archived_at,
        created_at=lead.created_at,
        updated_at=lead.updated_at,
    )


@router.post(
    "",
    response_model=LeadResponse,
    status_code=201,
    dependencies=[Depends(require(Permission.LEAD_WRITE))],
)
async def create_lead_route(
    payload: LeadCreateRequest,
    membership: Membership = Depends(get_current_membership),
    db: AsyncSession = Depends(get_db_session),
) -> LeadResponse:
    lead = await create_lead(
        db,
        organization_id=membership.organization_id,
        actor=membership,
        name=payload.name,
        company=payload.company,
        email=payload.email,
        phone=payload.phone,
        source=payload.source,
        service=payload.service,
        estimated_value=payload.estimated_value,
        currency=payload.currency,
        stage=payload.stage,
        assigned_to=payload.assigned_to,
        next_follow_up=payload.next_follow_up,
        notes=payload.notes,
    )
    return lead_to_response(lead)


@router.get(
    "", response_model=LeadListResponse, dependencies=[Depends(require(Permission.LEAD_READ))]
)
async def list_leads_route(
    stage: LeadStage | None = Query(default=None),
    assigned_to: uuid.UUID | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),  # ADR-0005: default 50, hard cap 200
    offset: int = Query(default=0, ge=0),
    membership: Membership = Depends(get_current_membership),
    db: AsyncSession = Depends(get_db_session),
) -> LeadListResponse:
    result = await list_leads(
        db,
        organization_id=membership.organization_id,
        actor=membership,
        stage=stage,
        assigned_to=assigned_to,
        limit=limit,
        offset=offset,
    )
    return LeadListResponse(
        items=[lead_to_response(lead) for lead in result.items], total=result.total
    )


@router.get(
    "/stats",
    response_model=LeadStatsResponse,
    dependencies=[Depends(require(Permission.LEAD_READ))],
)
async def get_lead_stats_route(
    membership: Membership = Depends(get_current_membership),
    db: AsyncSession = Depends(get_db_session),
) -> LeadStatsResponse:
    # Registered before /{lead_id} — a static path must be matched first,
    # or FastAPI would try to parse "stats" as a lead_id UUID path param.
    stats = await get_lead_stats(db, organization_id=membership.organization_id, actor=membership)
    return LeadStatsResponse(
        pipeline_value=stats.pipeline_value, follow_ups_due=stats.follow_ups_due
    )


@router.get(
    "/{lead_id}", response_model=LeadResponse, dependencies=[Depends(require(Permission.LEAD_READ))]
)
async def get_lead_route(
    lead_id: uuid.UUID,
    membership: Membership = Depends(get_current_membership),
    db: AsyncSession = Depends(get_db_session),
) -> LeadResponse:
    lead = await get_lead(
        db, organization_id=membership.organization_id, actor=membership, lead_id=lead_id
    )
    return lead_to_response(lead)


@router.patch(
    "/{lead_id}",
    response_model=LeadResponse,
    dependencies=[Depends(require(Permission.LEAD_WRITE))],
)
async def update_lead_route(
    lead_id: uuid.UUID,
    payload: LeadUpdateRequest,
    membership: Membership = Depends(get_current_membership),
    db: AsyncSession = Depends(get_db_session),
) -> LeadResponse:
    updates = payload.model_dump(exclude_unset=True)
    lead = await update_lead(
        db,
        organization_id=membership.organization_id,
        actor=membership,
        lead_id=lead_id,
        updates=updates,
    )
    return lead_to_response(lead)


@router.delete(
    "/{lead_id}",
    response_model=LeadResponse,
    dependencies=[Depends(require(Permission.LEAD_WRITE))],
)
async def archive_lead_route(
    lead_id: uuid.UUID,
    membership: Membership = Depends(get_current_membership),
    db: AsyncSession = Depends(get_db_session),
) -> LeadResponse:
    lead = await archive_lead(
        db, organization_id=membership.organization_id, actor=membership, lead_id=lead_id
    )
    return lead_to_response(lead)

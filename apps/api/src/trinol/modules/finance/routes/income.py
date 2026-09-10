from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from trinol.core.authz.permissions import Permission
from trinol.core.authz.require import require
from trinol.core.db.engine import get_db_session
from trinol.modules.finance.models import Income
from trinol.modules.finance.schemas import (
    IncomeCreateRequest,
    IncomeListResponse,
    IncomeResponse,
    IncomeUpdateRequest,
)
from trinol.modules.finance.services.income_service import (
    create_income,
    delete_income,
    get_income,
    list_income,
    update_income,
)
from trinol.modules.identity.deps import get_current_membership
from trinol.modules.identity.models import Membership

router = APIRouter(prefix="/api/v1/finance/income", tags=["finance"])


def income_to_response(income: Income) -> IncomeResponse:
    return IncomeResponse(
        id=income.id,
        amount=income.amount,
        currency=income.currency,
        source=income.source,
        client_id=income.client_id,
        project_id=income.project_id,
        invoice_id=income.invoice_id,
        received_on=income.received_on,
        payment_method=income.payment_method,
        reference=income.reference,
        notes=income.notes,
        created_by=income.created_by,
        created_at=income.created_at,
        updated_at=income.updated_at,
    )


@router.post(
    "",
    response_model=IncomeResponse,
    status_code=201,
    dependencies=[Depends(require(Permission.FINANCE_WRITE))],
)
async def create_income_route(
    payload: IncomeCreateRequest,
    membership: Membership = Depends(get_current_membership),
    db: AsyncSession = Depends(get_db_session),
) -> IncomeResponse:
    income = await create_income(
        db,
        organization_id=membership.organization_id,
        actor=membership,
        amount=payload.amount,
        currency=payload.currency,
        source=payload.source,
        client_id=payload.client_id,
        project_id=payload.project_id,
        invoice_id=payload.invoice_id,
        received_on=payload.received_on,
        payment_method=payload.payment_method,
        reference=payload.reference,
        notes=payload.notes,
    )
    return income_to_response(income)


@router.get(
    "", response_model=IncomeListResponse, dependencies=[Depends(require(Permission.FINANCE_READ))]
)
async def list_income_route(
    limit: int = Query(default=50, ge=1, le=200),  # ADR-0005: default 50, hard cap 200
    offset: int = Query(default=0, ge=0),
    membership: Membership = Depends(get_current_membership),
    db: AsyncSession = Depends(get_db_session),
) -> IncomeListResponse:
    result = await list_income(
        db, organization_id=membership.organization_id, actor=membership, limit=limit, offset=offset
    )
    return IncomeListResponse(
        items=[income_to_response(i) for i in result.items], total=result.total
    )


@router.get(
    "/{income_id}",
    response_model=IncomeResponse,
    dependencies=[Depends(require(Permission.FINANCE_READ))],
)
async def get_income_route(
    income_id: uuid.UUID,
    membership: Membership = Depends(get_current_membership),
    db: AsyncSession = Depends(get_db_session),
) -> IncomeResponse:
    income = await get_income(
        db, organization_id=membership.organization_id, actor=membership, income_id=income_id
    )
    return income_to_response(income)


@router.patch(
    "/{income_id}",
    response_model=IncomeResponse,
    dependencies=[Depends(require(Permission.FINANCE_WRITE))],
)
async def update_income_route(
    income_id: uuid.UUID,
    payload: IncomeUpdateRequest,
    membership: Membership = Depends(get_current_membership),
    db: AsyncSession = Depends(get_db_session),
) -> IncomeResponse:
    updates = payload.model_dump(exclude_unset=True)
    income = await update_income(
        db,
        organization_id=membership.organization_id,
        actor=membership,
        income_id=income_id,
        updates=updates,
    )
    return income_to_response(income)


@router.delete(
    "/{income_id}",
    status_code=204,
    dependencies=[Depends(require(Permission.FINANCE_WRITE))],
)
async def delete_income_route(
    income_id: uuid.UUID,
    membership: Membership = Depends(get_current_membership),
    db: AsyncSession = Depends(get_db_session),
) -> None:
    await delete_income(
        db, organization_id=membership.organization_id, actor=membership, income_id=income_id
    )

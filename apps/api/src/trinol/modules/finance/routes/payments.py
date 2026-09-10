from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from trinol.core.authz.permissions import Permission
from trinol.core.authz.require import require
from trinol.core.db.engine import get_db_session
from trinol.modules.finance.models import Payment
from trinol.modules.finance.schemas import (
    PaymentCreateRequest,
    PaymentListResponse,
    PaymentResponse,
)
from trinol.modules.finance.services.payment_service import list_payments, record_payment
from trinol.modules.identity.deps import get_current_membership
from trinol.modules.identity.models import Membership

# Nested under the parent invoice (DATABASE.md §3: a payment always
# belongs to exactly one invoice) — same shape as meetings' own
# sub-resource routers, just its own file per this phase's stage split.
router = APIRouter(prefix="/api/v1/finance/invoices/{invoice_id}/payments", tags=["finance"])


def payment_to_response(payment: Payment) -> PaymentResponse:
    return PaymentResponse(
        id=payment.id,
        invoice_id=payment.invoice_id,
        amount=payment.amount,
        currency=payment.currency,
        paid_on=payment.paid_on,
        method=payment.method,
        reference=payment.reference,
        recorded_by=payment.recorded_by,
        created_at=payment.created_at,
    )


@router.post(
    "",
    response_model=PaymentResponse,
    status_code=201,
    dependencies=[Depends(require(Permission.PAYMENT_WRITE))],
)
async def record_payment_route(
    invoice_id: uuid.UUID,
    payload: PaymentCreateRequest,
    membership: Membership = Depends(get_current_membership),
    db: AsyncSession = Depends(get_db_session),
) -> PaymentResponse:
    payment = await record_payment(
        db,
        organization_id=membership.organization_id,
        actor=membership,
        invoice_id=invoice_id,
        amount=payload.amount,
        currency=payload.currency,
        paid_on=payload.paid_on,
        method=payload.method,
        reference=payload.reference,
    )
    return payment_to_response(payment)


@router.get(
    "",
    response_model=PaymentListResponse,
    dependencies=[Depends(require(Permission.FINANCE_READ))],
)
async def list_payments_route(
    invoice_id: uuid.UUID,
    limit: int = Query(default=50, ge=1, le=200),  # ADR-0005: default 50, hard cap 200
    offset: int = Query(default=0, ge=0),
    membership: Membership = Depends(get_current_membership),
    db: AsyncSession = Depends(get_db_session),
) -> PaymentListResponse:
    result = await list_payments(
        db,
        organization_id=membership.organization_id,
        actor=membership,
        invoice_id=invoice_id,
        limit=limit,
        offset=offset,
    )
    return PaymentListResponse(
        items=[payment_to_response(p) for p in result.items], total=result.total
    )

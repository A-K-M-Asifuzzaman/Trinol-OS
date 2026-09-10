from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from trinol.core.db.org_session import OrgSession
from trinol.core.errors import ConflictError, ForbiddenError, UnprocessableEntityError
from trinol.core.ids import uuid7
from trinol.modules.finance.models import InvoiceStatus, Payment
from trinol.modules.finance.services.invoice_service import get_invoice_in_org
from trinol.modules.identity.models import Membership
from trinol.platform.activity import record

# Payments are only accepted against an invoice that has actually been
# sent — not DRAFT (never sent, nothing to pay yet) and not CANCELLED (a
# cancelled invoice is done). A fully PAID invoice is rejected too, but
# that falls out of the overpayment check below rather than needing its
# own branch here.
_PAYABLE_STATUSES = (InvoiceStatus.SENT, InvoiceStatus.PARTIALLY_PAID)


@dataclass(frozen=True, slots=True)
class PaymentList:
    items: list[Payment]
    total: int


def ensure_actor_in_org(actor: Membership, organization_id: uuid.UUID) -> None:
    """Defense in depth, same reasoning as every other module's own copy of
    this check (e.g. income_service's own copy)."""
    if actor.organization_id != organization_id:
        raise ForbiddenError("Actor does not belong to this organization")


async def _sum_payments(
    db: AsyncSession, *, organization_id: uuid.UUID, invoice_id: uuid.UUID
) -> Decimal:
    result = await db.execute(
        select(func.coalesce(func.sum(Payment.amount), 0)).where(
            Payment.organization_id == organization_id, Payment.invoice_id == invoice_id
        )
    )
    return result.scalar_one()


def _derive_status(*, total_paid: Decimal, invoice_total: Decimal) -> InvoiceStatus:
    return InvoiceStatus.PAID if total_paid >= invoice_total else InvoiceStatus.PARTIALLY_PAID


async def record_payment(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    actor: Membership,
    invoice_id: uuid.UUID,
    amount: Decimal,
    currency: str,
    paid_on: date,
    method: str,
    reference: str | None,
) -> Payment:
    """ADR-0007: 'Recording a payment first locks the invoice row with
    SELECT ... FOR UPDATE, then recomputes amount_paid as the sum of
    payments and moves the status to PARTIALLY_PAID or PAID from that
    sum. Overpayment beyond the total is rejected with a 409.' The lock is
    taken before the balance is even read, so a second concurrent request
    blocks until the first commits, then sees the already-updated sum
    instead of racing against a stale one (same fix shape as
    `send_invoice`/`cancel_invoice`/`lead_conversion_service.
    convert_lead`) — the exact property ADR-0007's own consequences
    section requires a concurrent-payment test to prove."""
    ensure_actor_in_org(actor, organization_id)
    if amount <= 0:
        raise UnprocessableEntityError("amount must be greater than 0")

    invoice = await get_invoice_in_org(
        db, organization_id=organization_id, invoice_id=invoice_id, for_update=True
    )
    if invoice.status not in _PAYABLE_STATUSES:
        raise ConflictError(
            f"Cannot record a payment against an invoice with status {invoice.status.value}"
        )

    existing_total = await _sum_payments(db, organization_id=organization_id, invoice_id=invoice_id)
    new_total_paid = existing_total + amount
    if new_total_paid > invoice.total:
        raise ConflictError("Payment would exceed the invoice's remaining balance")

    org_session = OrgSession(db, organization_id=organization_id)
    payment = Payment(
        id=uuid7(),
        invoice_id=invoice_id,
        amount=amount,
        currency=currency,
        paid_on=paid_on,
        method=method,
        reference=reference,
        recorded_by=actor.user_id,
    )
    org_session.add(payment)

    invoice.amount_paid = new_total_paid
    invoice.status = _derive_status(total_paid=new_total_paid, invoice_total=invoice.total)

    await record(
        db,
        organization_id=organization_id,
        event="payment.recorded",
        entity_type="payment",
        entity_id=payment.id,
        actor_id=actor.user_id,
        metadata={"invoice_id": str(invoice_id), "amount": str(amount)},
    )
    await db.commit()
    return payment


async def list_payments(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    actor: Membership,
    invoice_id: uuid.UUID,
    limit: int = 50,
    offset: int = 0,
) -> PaymentList:
    ensure_actor_in_org(actor, organization_id)
    # 404s a cross-org/missing invoice before ever listing its payments —
    # same reasoning every sub-resource list already applies to its parent.
    await get_invoice_in_org(db, organization_id=organization_id, invoice_id=invoice_id)

    total_result = await db.execute(
        select(func.count())
        .select_from(Payment)
        .where(Payment.organization_id == organization_id, Payment.invoice_id == invoice_id)
    )
    total = total_result.scalar_one()

    org_session = OrgSession(db, organization_id=organization_id)
    result = await db.execute(
        org_session.select(Payment)
        .where(Payment.invoice_id == invoice_id)
        .order_by(Payment.created_at.asc(), Payment.id.asc())
        .limit(limit)
        .offset(offset)
    )
    return PaymentList(items=list(result.scalars().all()), total=total)

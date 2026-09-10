from __future__ import annotations

import logging
import re
import uuid
from datetime import date
from urllib.parse import quote

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from fastapi import Response as FastAPIResponse
from sqlalchemy.ext.asyncio import AsyncSession

from trinol.core.authz.permissions import Permission
from trinol.core.authz.require import require
from trinol.core.db.engine import get_db_session
from trinol.modules.finance.models import Invoice, InvoiceItem, InvoiceStatus
from trinol.modules.finance.schemas import (
    InvoiceCreateRequest,
    InvoiceItemResponse,
    InvoiceLineItemInput,
    InvoiceListResponse,
    InvoiceResponse,
    InvoiceUpdateRequest,
)
from trinol.modules.finance.services.invoice_service import (
    InvoiceWithItems,
    LineItemInput,
    cancel_invoice,
    create_invoice,
    generate_invoice_pdf,
    get_invoice,
    list_invoices,
    send_invoice,
    update_invoice,
)
from trinol.modules.identity.deps import get_current_membership
from trinol.modules.identity.models import Membership
from trinol.platform.email.deps import get_email_sender
from trinol.platform.email.protocol import EmailMessage, EmailSender

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/finance/invoices", tags=["finance"])

_OVERDUE_STATUSES = (InvoiceStatus.SENT, InvoiceStatus.PARTIALLY_PAID)


def _is_overdue(invoice: Invoice) -> bool:
    """ADR-0007: derived on read, never stored — 'status IN (SENT,
    PARTIALLY_PAID) AND due_date < today'."""
    return invoice.status in _OVERDUE_STATUSES and invoice.due_date < date.today()


def _item_to_response(item: InvoiceItem) -> InvoiceItemResponse:
    return InvoiceItemResponse(
        id=item.id,
        description=item.description,
        quantity=item.quantity,
        unit_price=item.unit_price,
        line_total=item.line_total,
        position=item.position,
    )


def _to_line_item_inputs(items: list[InvoiceLineItemInput]) -> list[LineItemInput]:
    return [
        LineItemInput(description=i.description, quantity=i.quantity, unit_price=i.unit_price)
        for i in items
    ]


def invoice_to_response(pair: InvoiceWithItems) -> InvoiceResponse:
    invoice = pair.invoice
    return InvoiceResponse(
        id=invoice.id,
        invoice_number=invoice.invoice_number,
        client_id=invoice.client_id,
        project_id=invoice.project_id,
        issue_date=invoice.issue_date,
        due_date=invoice.due_date,
        currency=invoice.currency,
        items=[_item_to_response(i) for i in pair.items],
        subtotal=invoice.subtotal,
        discount_amount=invoice.discount_amount,
        tax_amount=invoice.tax_amount,
        total=invoice.total,
        amount_paid=invoice.amount_paid,
        status=invoice.status,
        is_overdue=_is_overdue(invoice),
        notes=invoice.notes,
        terms=invoice.terms,
        sent_at=invoice.sent_at,
        created_by=invoice.created_by,
        created_at=invoice.created_at,
        updated_at=invoice.updated_at,
    )


@router.post(
    "",
    response_model=InvoiceResponse,
    status_code=201,
    dependencies=[Depends(require(Permission.INVOICE_WRITE))],
)
async def create_invoice_route(
    payload: InvoiceCreateRequest,
    membership: Membership = Depends(get_current_membership),
    db: AsyncSession = Depends(get_db_session),
) -> InvoiceResponse:
    pair = await create_invoice(
        db,
        organization_id=membership.organization_id,
        actor=membership,
        client_id=payload.client_id,
        project_id=payload.project_id,
        issue_date=payload.issue_date,
        due_date=payload.due_date,
        currency=payload.currency,
        items=_to_line_item_inputs(payload.items),
        discount_amount=payload.discount_amount,
        tax_amount=payload.tax_amount,
        notes=payload.notes,
        terms=payload.terms,
    )
    return invoice_to_response(pair)


@router.get(
    "",
    response_model=InvoiceListResponse,
    dependencies=[Depends(require(Permission.FINANCE_READ))],
)
async def list_invoices_route(
    limit: int = Query(default=50, ge=1, le=200),  # ADR-0005: default 50, hard cap 200
    offset: int = Query(default=0, ge=0),
    membership: Membership = Depends(get_current_membership),
    db: AsyncSession = Depends(get_db_session),
) -> InvoiceListResponse:
    result = await list_invoices(
        db, organization_id=membership.organization_id, actor=membership, limit=limit, offset=offset
    )
    return InvoiceListResponse(
        items=[invoice_to_response(p) for p in result.items], total=result.total
    )


@router.get(
    "/{invoice_id}",
    response_model=InvoiceResponse,
    dependencies=[Depends(require(Permission.FINANCE_READ))],
)
async def get_invoice_route(
    invoice_id: uuid.UUID,
    membership: Membership = Depends(get_current_membership),
    db: AsyncSession = Depends(get_db_session),
) -> InvoiceResponse:
    pair = await get_invoice(
        db, organization_id=membership.organization_id, actor=membership, invoice_id=invoice_id
    )
    return invoice_to_response(pair)


def _content_disposition(filename: str) -> str:
    """Same encoding as work.routes.tasks/finance.routes.expenses' own
    copy — RFC 6266's `filename*` form percent-encodes the entire name so
    an invoice_number containing `"`, `\\`, or a control byte can't break
    out of the header, with a stripped-down ASCII fallback for older
    clients."""
    ascii_fallback = re.sub(r"[^A-Za-z0-9 ._-]", "_", filename).strip() or "invoice"
    encoded = quote(filename, safe="")
    return f"attachment; filename=\"{ascii_fallback}\"; filename*=UTF-8''{encoded}"


@router.get(
    "/{invoice_id}/pdf",
    dependencies=[Depends(require(Permission.FINANCE_READ))],
)
async def get_invoice_pdf_route(
    invoice_id: uuid.UUID,
    membership: Membership = Depends(get_current_membership),
    db: AsyncSession = Depends(get_db_session),
) -> FastAPIResponse:
    # Read-only (FINANCE_READ, not INVOICE_WRITE) — viewing an existing
    # invoice's PDF is a read, no separate "download" permission invented.
    pdf = await generate_invoice_pdf(
        db, organization_id=membership.organization_id, actor=membership, invoice_id=invoice_id
    )
    return FastAPIResponse(
        content=pdf.data,
        media_type="application/pdf",
        headers={
            "Content-Disposition": _content_disposition(f"{pdf.invoice_number}.pdf"),
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.patch(
    "/{invoice_id}",
    response_model=InvoiceResponse,
    dependencies=[Depends(require(Permission.INVOICE_WRITE))],
)
async def update_invoice_route(
    invoice_id: uuid.UUID,
    payload: InvoiceUpdateRequest,
    membership: Membership = Depends(get_current_membership),
    db: AsyncSession = Depends(get_db_session),
) -> InvoiceResponse:
    updates = payload.model_dump(exclude_unset=True)
    if payload.items is not None:
        updates["items"] = _to_line_item_inputs(payload.items)
    pair = await update_invoice(
        db,
        organization_id=membership.organization_id,
        actor=membership,
        invoice_id=invoice_id,
        updates=updates,
    )
    return invoice_to_response(pair)


async def _send_with_retry(sender: EmailSender, message: EmailMessage) -> None:
    """Codex P1: a bare `background_tasks.add_task(sender.send, message)`
    (invitations.invite_member's own pattern) relies on a real ASGI server
    swallowing a background task's exception after the response is
    already on the wire — crm.routes.public.py's own `_send_and_log_
    failures` already found and documented that Starlette's TestClient/
    ASGITransport has no such boundary and re-raises straight into the
    caller. An invoice failing to send is worth one immediate retry (a
    transient SMTP blip shouldn't burn the only attempt) before giving up
    and logging — stronger than the contact flow's own catch-and-log-only
    wrapper, so it isn't reused as-is."""
    try:
        await sender.send(message)
        return
    except Exception:
        logger.warning("Invoice email send failed, retrying once", exc_info=True)
    try:
        await sender.send(message)
    except Exception:
        logger.exception("Failed to send invoice email after one retry")


@router.post(
    "/{invoice_id}/send",
    response_model=InvoiceResponse,
    dependencies=[Depends(require(Permission.INVOICE_WRITE))],
)
async def send_invoice_route(
    invoice_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    membership: Membership = Depends(get_current_membership),
    db: AsyncSession = Depends(get_db_session),
    sender: EmailSender = Depends(get_email_sender),
) -> InvoiceResponse:
    result = await send_invoice(
        db, organization_id=membership.organization_id, actor=membership, invoice_id=invoice_id
    )
    # EMAIL.md §3: dispatched only after send_invoice's own commit above,
    # never blocking or failing this response.
    background_tasks.add_task(_send_with_retry, sender, result.email_message)
    return invoice_to_response(result.invoice_with_items)


@router.post(
    "/{invoice_id}/cancel",
    response_model=InvoiceResponse,
    dependencies=[Depends(require(Permission.INVOICE_CANCEL))],
)
async def cancel_invoice_route(
    invoice_id: uuid.UUID,
    membership: Membership = Depends(get_current_membership),
    db: AsyncSession = Depends(get_db_session),
) -> InvoiceResponse:
    pair = await cancel_invoice(
        db, organization_id=membership.organization_id, actor=membership, invoice_id=invoice_id
    )
    return invoice_to_response(pair)

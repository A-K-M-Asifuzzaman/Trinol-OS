from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from trinol.core.db.org_session import OrgSession
from trinol.core.deps import get_settings
from trinol.core.errors import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    UnprocessableEntityError,
)
from trinol.core.ids import uuid7
from trinol.modules.crm.services.client_service import get_client_in_org
from trinol.modules.finance.models import Invoice, InvoiceItem, InvoiceStatus
from trinol.modules.finance.services.invoice_counter_service import next_invoice_number
from trinol.modules.identity.models import Membership, Organization
from trinol.modules.work.services.project_service import get_project_in_org
from trinol.platform.activity import record
from trinol.platform.email.protocol import EmailMessage
from trinol.platform.email.render import render_invoice_email
from trinol.platform.pdf.render import InvoicePdfLineItem, render_invoice_pdf


@dataclass(frozen=True, slots=True)
class LineItemInput:
    """Service-layer shape for a line item — deliberately not the Pydantic
    `InvoiceLineItemInput` (no service in this codebase imports from its
    own module's schemas.py); `routes/invoices.py` maps one to the other."""

    description: str
    quantity: Decimal
    unit_price: Decimal


@dataclass(frozen=True, slots=True)
class InvoiceWithItems:
    invoice: Invoice
    items: list[InvoiceItem]


@dataclass(frozen=True, slots=True)
class InvoiceList:
    items: list[InvoiceWithItems]
    total: int


@dataclass(frozen=True, slots=True)
class InvoiceSendResult:
    """Pairs the now-SENT invoice with its pre-built (never yet sent)
    email — same shape as identity.services.invitation_service's own
    `CreatedInvitation`. The route dispatches `email_message` via
    `BackgroundTasks` *after* this function's own commit (EMAIL.md §3);
    this function only builds the message, never sends it."""

    invoice_with_items: InvoiceWithItems
    email_message: EmailMessage


def ensure_actor_in_org(actor: Membership, organization_id: uuid.UUID) -> None:
    """Defense in depth, same reasoning as every other module's own copy of
    this check (e.g. income_service's own copy)."""
    if actor.organization_id != organization_id:
        raise ForbiddenError("Actor does not belong to this organization")


def _round_money(value: Decimal) -> Decimal:
    """ADR-0007: 'Decimal context is set explicitly with ROUND_HALF_UP.'
    Python's bare `round()`/`Decimal.__round__` uses the *current decimal
    context*, whose default rounding mode is ROUND_HALF_EVEN (banker's
    rounding) — silently different from Postgres's own `round(numeric,
    int)` (round half away from zero, equivalent to ROUND_HALF_UP for the
    non-negative amounts here) on an exact .xx5 boundary. `quantize` with
    an explicit rounding mode is the only way to guarantee the two agree,
    which `ck_line_total`'s own DB-level check depends on."""
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


async def get_invoice_in_org(
    db: AsyncSession, *, organization_id: uuid.UUID, invoice_id: uuid.UUID, for_update: bool = False
) -> Invoice:
    """Org-scoped lookup — 404s a cross-org id exactly like a missing one
    (RBAC.md §4), same pattern as income_service.get_income_in_org.
    `for_update`: takes a row lock for a check-then-write status
    transition — `send_invoice`/`cancel_invoice`'s own status checks
    (Codex P1: two concurrent requests could otherwise both observe the
    same pre-transition status and both act on it, producing duplicate
    `invoice.sent`/`invoice.cancelled` events and, for send, duplicate
    emails) and `record_payment`'s own balance recompute (Stage 7) —
    same reason as lead_service.get_lead_in_org's own `for_update`
    param."""
    stmt = (
        select(Invoice)
        .where(Invoice.organization_id == organization_id, Invoice.id == invoice_id)
        .execution_options(populate_existing=True)
    )
    if for_update:
        stmt = stmt.with_for_update()
    result = await db.execute(stmt)
    invoice = result.scalar_one_or_none()
    if invoice is None:
        raise NotFoundError("Invoice not found")
    return invoice


async def get_invoice_items_in_org(
    db: AsyncSession, *, organization_id: uuid.UUID, invoice_id: uuid.UUID
) -> list[InvoiceItem]:
    result = await db.execute(
        select(InvoiceItem)
        .where(InvoiceItem.organization_id == organization_id, InvoiceItem.invoice_id == invoice_id)
        .order_by(InvoiceItem.position.asc())
    )
    return list(result.scalars().all())


async def _load_invoice_with_items(
    db: AsyncSession, *, organization_id: uuid.UUID, invoice_id: uuid.UUID
) -> InvoiceWithItems:
    invoice = await get_invoice_in_org(db, organization_id=organization_id, invoice_id=invoice_id)
    items = await get_invoice_items_in_org(
        db, organization_id=organization_id, invoice_id=invoice_id
    )
    return InvoiceWithItems(invoice=invoice, items=items)


async def _validate_references(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    client_id: uuid.UUID,
    project_id: uuid.UUID | None,
) -> None:
    await get_client_in_org(db, organization_id=organization_id, client_id=client_id)
    if project_id is not None:
        await get_project_in_org(db, organization_id=organization_id, project_id=project_id)


def _compute_line_items(
    items: list[LineItemInput],
) -> tuple[list[tuple[LineItemInput, Decimal, int]], Decimal]:
    """Rounds each line once (`line_total = round(quantity * unit_price,
    2)`), then sums — never the reverse (ADR-0007)."""
    computed = []
    subtotal = Decimal("0")
    for position, item in enumerate(items):
        line_total = _round_money(item.quantity * item.unit_price)
        computed.append((item, line_total, position))
        subtotal += line_total
    return computed, subtotal


def _validate_amounts(
    *, subtotal: Decimal, discount_amount: Decimal, tax_amount: Decimal
) -> Decimal:
    """Mirrors `ck_invoice_amounts`/`ck_invoice_total` at the application
    layer too (same reasoning as every other module's own pre-insert
    check) — a clean 422 instead of a raw DB `CheckViolationError`. ADR-
    0007's own consequences section explicitly calls out 'a discount
    larger than a line' as a required test case; this is what catches it."""
    if discount_amount < 0 or tax_amount < 0:
        raise UnprocessableEntityError("discount_amount and tax_amount must be non-negative")
    if subtotal < 0:
        raise UnprocessableEntityError("subtotal must be non-negative")
    total = subtotal - discount_amount + tax_amount
    if total < 0:
        raise UnprocessableEntityError(
            "total cannot be negative — discount_amount exceeds subtotal plus tax_amount"
        )
    return total


async def create_invoice(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    actor: Membership,
    client_id: uuid.UUID,
    project_id: uuid.UUID | None,
    issue_date: date,
    due_date: date,
    currency: str,
    items: list[LineItemInput],
    discount_amount: Decimal,
    tax_amount: Decimal,
    notes: str | None,
    terms: str | None,
) -> InvoiceWithItems:
    # RBAC.md §2: "Invoices: create/send" is ADMIN+-tier, flat — the
    # route's own require(Permission.INVOICE_WRITE) is the entire
    # authorization check (ROADMAP.md Phase 5 decision 2), same reasoning
    # as income_service.create_income.
    ensure_actor_in_org(actor, organization_id)
    await _validate_references(
        db, organization_id=organization_id, client_id=client_id, project_id=project_id
    )
    if due_date < issue_date:
        # Mirrors ck_invoice_dates at the application layer too.
        raise UnprocessableEntityError("due_date must be on or after issue_date")

    computed_items, subtotal = _compute_line_items(items)
    total = _validate_amounts(
        subtotal=subtotal, discount_amount=discount_amount, tax_amount=tax_amount
    )

    invoice_number = await next_invoice_number(
        db, organization_id=organization_id, year=issue_date.year
    )

    org_session = OrgSession(db, organization_id=organization_id)
    invoice = Invoice(
        id=uuid7(),
        invoice_number=invoice_number,
        client_id=client_id,
        project_id=project_id,
        issue_date=issue_date,
        due_date=due_date,
        currency=currency,
        subtotal=subtotal,
        discount_amount=discount_amount,
        tax_amount=tax_amount,
        total=total,
        status=InvoiceStatus.DRAFT,
        notes=notes,
        terms=terms,
        created_by=actor.user_id,
    )
    org_session.add(invoice)
    await db.flush()

    for item, line_total, position in computed_items:
        org_session.add(
            InvoiceItem(
                id=uuid7(),
                invoice_id=invoice.id,
                description=item.description,
                quantity=item.quantity,
                unit_price=item.unit_price,
                line_total=line_total,
                position=position,
            )
        )

    await record(
        db,
        organization_id=organization_id,
        event="invoice.created",
        entity_type="invoice",
        entity_id=invoice.id,
        actor_id=actor.user_id,
        metadata={"invoice_number": invoice.invoice_number, "total": str(invoice.total)},
    )
    await db.commit()
    return await _load_invoice_with_items(
        db, organization_id=organization_id, invoice_id=invoice.id
    )


async def list_invoices(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    actor: Membership,
    limit: int = 50,
    offset: int = 0,
) -> InvoiceList:
    ensure_actor_in_org(actor, organization_id)

    # ADR-0011: invoices are one of the four archived_at entities — no
    # route sets it in V1 (ROADMAP.md Phase 5 decision 1), but the list
    # query filters defensively anyway, same discipline as every other
    # soft-deletable entity's own list query.
    total_result = await db.execute(
        select(func.count())
        .select_from(Invoice)
        .where(Invoice.organization_id == organization_id, Invoice.archived_at.is_(None))
    )
    total = total_result.scalar_one()

    org_session = OrgSession(db, organization_id=organization_id)
    result = await db.execute(
        org_session.select(Invoice)
        .where(Invoice.archived_at.is_(None))
        .order_by(Invoice.issue_date.desc(), Invoice.id.asc())
        .limit(limit)
        .offset(offset)
    )
    invoices = list(result.scalars().all())

    items_result = await db.execute(
        select(InvoiceItem)
        .where(
            InvoiceItem.organization_id == organization_id,
            InvoiceItem.invoice_id.in_([inv.id for inv in invoices]),
        )
        .order_by(InvoiceItem.invoice_id.asc(), InvoiceItem.position.asc())
    )
    items_by_invoice: dict[uuid.UUID, list[InvoiceItem]] = defaultdict(list)
    for item in items_result.scalars().all():
        items_by_invoice[item.invoice_id].append(item)

    return InvoiceList(
        items=[
            InvoiceWithItems(invoice=inv, items=items_by_invoice.get(inv.id, []))
            for inv in invoices
        ],
        total=total,
    )


async def get_invoice(
    db: AsyncSession, *, organization_id: uuid.UUID, actor: Membership, invoice_id: uuid.UUID
) -> InvoiceWithItems:
    ensure_actor_in_org(actor, organization_id)
    return await _load_invoice_with_items(
        db, organization_id=organization_id, invoice_id=invoice_id
    )


async def update_invoice(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    actor: Membership,
    invoice_id: uuid.UUID,
    updates: dict[str, Any],
) -> InvoiceWithItems:
    """ADR-0007: 'A DRAFT invoice is freely editable. Once SENT, financial
    fields are frozen.' Implemented as a whole-invoice lock once non-DRAFT
    — simpler and stricter than field-by-field, matching the plan's own
    'update_invoice — only while status == DRAFT' framing rather than
    inventing a partial-freeze not asked for anywhere."""
    ensure_actor_in_org(actor, organization_id)
    invoice = await get_invoice_in_org(db, organization_id=organization_id, invoice_id=invoice_id)
    if invoice.status != InvoiceStatus.DRAFT:
        raise ConflictError("Only a DRAFT invoice may be edited")

    client_id = updates.get("client_id", invoice.client_id)
    project_id = updates.get("project_id", invoice.project_id)
    await _validate_references(
        db, organization_id=organization_id, client_id=client_id, project_id=project_id
    )

    issue_date = updates.get("issue_date", invoice.issue_date)
    due_date = updates.get("due_date", invoice.due_date)
    if due_date < issue_date:
        raise UnprocessableEntityError("due_date must be on or after issue_date")

    discount_amount = updates.get("discount_amount", invoice.discount_amount)
    tax_amount = updates.get("tax_amount", invoice.tax_amount)

    existing_items = await get_invoice_items_in_org(
        db, organization_id=organization_id, invoice_id=invoice.id
    )

    new_items = updates.get("items")
    if new_items is not None:
        computed_items, subtotal = _compute_line_items(new_items)
    else:
        computed_items = None
        subtotal = sum((row.line_total for row in existing_items), Decimal("0"))

    total = _validate_amounts(
        subtotal=subtotal, discount_amount=discount_amount, tax_amount=tax_amount
    )

    for field in (
        "client_id",
        "project_id",
        "issue_date",
        "due_date",
        "currency",
        "discount_amount",
        "tax_amount",
        "notes",
        "terms",
    ):
        if field in updates:
            setattr(invoice, field, updates[field])
    invoice.subtotal = subtotal
    invoice.total = total

    if computed_items is not None:
        for row in existing_items:
            await db.delete(row)
        await db.flush()
        org_session = OrgSession(db, organization_id=organization_id)
        for item, line_total, position in computed_items:
            org_session.add(
                InvoiceItem(
                    id=uuid7(),
                    invoice_id=invoice.id,
                    description=item.description,
                    quantity=item.quantity,
                    unit_price=item.unit_price,
                    line_total=line_total,
                    position=position,
                )
            )

    await db.commit()
    return await _load_invoice_with_items(
        db, organization_id=organization_id, invoice_id=invoice_id
    )


async def send_invoice(
    db: AsyncSession, *, organization_id: uuid.UUID, actor: Membership, invoice_id: uuid.UUID
) -> InvoiceSendResult:
    """ADR-0007: 'Once SENT, financial fields are frozen' — `update_invoice`
    already enforces that once `status != DRAFT`. RBAC.md's "Invoices:
    create/send" is one row/one permission (`INVOICE_WRITE`) covering both
    this and `create_invoice`. The email is rendered and the entity
    committed here; the route dispatches it via `BackgroundTasks`
    (ROADMAP.md's own tech-debt row: no persistent email outbox, no queue,
    same synchronous `EmailSender` pipeline every other email uses).

    Codex P1: the DRAFT check was a bare check-then-write with no lock —
    two concurrent sends of the same invoice could both pass it, each
    transition it and each dispatch its own email. `for_update=True` takes
    a row lock first; the second request blocks until the first commits,
    then sees `status` already `SENT` and 409s instead of racing (same
    fix shape as `lead_conversion_service.convert_lead`)."""
    ensure_actor_in_org(actor, organization_id)
    invoice = await get_invoice_in_org(
        db, organization_id=organization_id, invoice_id=invoice_id, for_update=True
    )
    if invoice.status != InvoiceStatus.DRAFT:
        raise ConflictError("Only a DRAFT invoice can be sent")

    client = await get_client_in_org(
        db, organization_id=organization_id, client_id=invoice.client_id
    )
    if not client.email:
        raise UnprocessableEntityError(
            "This client has no email address on file — add one before sending"
        )

    org_result = await db.execute(select(Organization).where(Organization.id == organization_id))
    organization = org_result.scalar_one()

    invoice.status = InvoiceStatus.SENT
    invoice.sent_at = datetime.now(UTC)

    await record(
        db,
        organization_id=organization_id,
        event="invoice.sent",
        entity_type="invoice",
        entity_id=invoice.id,
        actor_id=actor.user_id,
        metadata={"invoice_number": invoice.invoice_number},
    )

    settings = get_settings()
    html_body, text_body = render_invoice_email(
        organization_name=organization.name,
        client_name=client.name,
        invoice_number=invoice.invoice_number,
        issue_date=invoice.issue_date.isoformat(),
        due_date=invoice.due_date.isoformat(),
        currency=invoice.currency,
        total=str(invoice.total),
        view_url=f"{settings.app_origin}/invoices/{invoice.id}",
    )
    email_message = EmailMessage(
        to=client.email,
        subject=f"Invoice {invoice.invoice_number} from {organization.name}",
        html_body=html_body,
        text_body=text_body,
    )

    await db.commit()
    pair = await _load_invoice_with_items(
        db, organization_id=organization_id, invoice_id=invoice_id
    )
    return InvoiceSendResult(invoice_with_items=pair, email_message=email_message)


# Cancellable: everything except the two terminal states — an invoice that
# is already fully PAID or already CANCELLED can't be cancelled again.
_TERMINAL_STATUSES = (InvoiceStatus.PAID, InvoiceStatus.CANCELLED)


async def cancel_invoice(
    db: AsyncSession, *, organization_id: uuid.UUID, actor: Membership, invoice_id: uuid.UUID
) -> InvoiceWithItems:
    """ADR-0007: 'Cancellation is a status change with an audit event,
    never a delete.' Gated by its own `INVOICE_CANCEL` permission
    (RBAC.md's own separate 'Invoice: cancel' row), distinct from
    `INVOICE_WRITE`.

    Codex P1: same race as `send_invoice` — `for_update=True` locks the
    row before the terminal-status check, so two concurrent cancels (or a
    cancel racing a send) can't both observe the same pre-transition
    status and both act on it."""
    ensure_actor_in_org(actor, organization_id)
    invoice = await get_invoice_in_org(
        db, organization_id=organization_id, invoice_id=invoice_id, for_update=True
    )
    if invoice.status in _TERMINAL_STATUSES:
        raise ConflictError(
            f"An invoice that is already {invoice.status.value} cannot be cancelled"
        )

    invoice.status = InvoiceStatus.CANCELLED

    await record(
        db,
        organization_id=organization_id,
        event="invoice.cancelled",
        entity_type="invoice",
        entity_id=invoice.id,
        actor_id=actor.user_id,
        metadata={"invoice_number": invoice.invoice_number},
        audit=True,
    )
    await db.commit()
    return await _load_invoice_with_items(
        db, organization_id=organization_id, invoice_id=invoice_id
    )


@dataclass(frozen=True, slots=True)
class InvoicePdf:
    data: bytes
    invoice_number: str


async def generate_invoice_pdf(
    db: AsyncSession, *, organization_id: uuid.UUID, actor: Membership, invoice_id: uuid.UUID
) -> InvoicePdf:
    """Gathers the invoice, its items, its client, and the organization
    name, then hands plain display values to `platform.pdf.render.
    render_invoice_pdf` (which stays decoupled from this module's ORM
    models, same reasoning `send_invoice` already applies for the email
    body). Read-only — gated by `FINANCE_READ` at the route, not
    `INVOICE_WRITE` (viewing an existing invoice's PDF is a read).
    `invoice_number` rides along so the route can build a real download
    filename without a second fetch, same reasoning task_attachment_
    service's own download path returns the FileObject alongside the
    bytes."""
    ensure_actor_in_org(actor, organization_id)
    pair = await _load_invoice_with_items(
        db, organization_id=organization_id, invoice_id=invoice_id
    )
    invoice = pair.invoice
    client = await get_client_in_org(
        db, organization_id=organization_id, client_id=invoice.client_id
    )
    org_result = await db.execute(select(Organization).where(Organization.id == organization_id))
    organization = org_result.scalar_one()

    data = render_invoice_pdf(
        organization_name=organization.name,
        client_name=client.name,
        client_company=client.company,
        client_address=client.address,
        client_email=client.email,
        invoice_number=invoice.invoice_number,
        status=invoice.status.value,
        issue_date=invoice.issue_date.isoformat(),
        due_date=invoice.due_date.isoformat(),
        currency=invoice.currency,
        items=[
            InvoicePdfLineItem(
                description=item.description,
                quantity=str(item.quantity),
                unit_price=str(item.unit_price),
                line_total=str(item.line_total),
            )
            for item in pair.items
        ],
        subtotal=str(invoice.subtotal),
        discount_amount=str(invoice.discount_amount),
        tax_amount=str(invoice.tax_amount),
        total=str(invoice.total),
        notes=invoice.notes,
        terms=invoice.terms,
    )
    return InvoicePdf(data=data, invoice_number=invoice.invoice_number)

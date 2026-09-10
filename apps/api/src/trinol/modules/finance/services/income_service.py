from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from trinol.core.db.org_session import OrgSession
from trinol.core.errors import ForbiddenError, NotFoundError, UnprocessableEntityError
from trinol.core.ids import uuid7
from trinol.modules.crm.services.client_service import get_client_in_org
from trinol.modules.finance.models import Income, Invoice
from trinol.modules.identity.models import Membership
from trinol.modules.work.services.project_service import get_project_in_org
from trinol.platform.activity import record


@dataclass(frozen=True, slots=True)
class IncomeList:
    items: list[Income]
    total: int


def ensure_actor_in_org(actor: Membership, organization_id: uuid.UUID) -> None:
    """Defense in depth, same reasoning as every other module's own copy of
    this check (e.g. work.services.project_service.ensure_actor_in_org)."""
    if actor.organization_id != organization_id:
        raise ForbiddenError("Actor does not belong to this organization")


async def _get_invoice_in_org(
    db: AsyncSession, *, organization_id: uuid.UUID, invoice_id: uuid.UUID
) -> Invoice:
    """Deliberately duplicated as a private lookup rather than importing
    from invoice_service.py — that module (Stage 4) doesn't exist yet.
    Stage 4 should replace this with a shared `get_invoice_in_org` once it
    defines one, the same consolidation Stage 3 will do for expenses'
    equivalent lookups."""
    result = await db.execute(
        select(Invoice).where(Invoice.organization_id == organization_id, Invoice.id == invoice_id)
    )
    invoice = result.scalar_one_or_none()
    if invoice is None:
        raise NotFoundError("Invoice not found")
    return invoice


async def _validate_references(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    client_id: uuid.UUID | None,
    project_id: uuid.UUID | None,
    invoice_id: uuid.UUID | None,
) -> None:
    if client_id is not None:
        await get_client_in_org(db, organization_id=organization_id, client_id=client_id)
    if project_id is not None:
        await get_project_in_org(db, organization_id=organization_id, project_id=project_id)
    if invoice_id is not None:
        await _get_invoice_in_org(db, organization_id=organization_id, invoice_id=invoice_id)


async def get_income_in_org(
    db: AsyncSession, *, organization_id: uuid.UUID, income_id: uuid.UUID
) -> Income:
    """Org-scoped lookup — 404s a cross-org id exactly like a missing one
    (RBAC.md §4), same pattern as get_client_in_org/get_project_in_org."""
    result = await db.execute(
        select(Income)
        .where(Income.organization_id == organization_id, Income.id == income_id)
        .execution_options(populate_existing=True)
    )
    income = result.scalar_one_or_none()
    if income is None:
        raise NotFoundError("Income not found")
    return income


async def create_income(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    actor: Membership,
    amount: Any,
    currency: str,
    source: str,
    client_id: uuid.UUID | None,
    project_id: uuid.UUID | None,
    invoice_id: uuid.UUID | None,
    received_on: date,
    payment_method: str,
    reference: str | None,
    notes: str | None,
) -> Income:
    # RBAC.md §2: "Income/expenses: write" is ADMIN+-tier, flat — the route's
    # own require(Permission.FINANCE_WRITE) is the entire authorization
    # check (ROADMAP.md Phase 5 decision 2: no ownership split anywhere in
    # this module), so unlike client/meeting create there's no role check
    # to repeat here.
    ensure_actor_in_org(actor, organization_id)
    if amount <= 0:
        # Mirrors ck_income_amount_positive at the application layer too
        # (same reasoning as meeting_service's ends_at/starts_at check) —
        # surfaces as a clean 422 instead of a raw DB CheckViolationError.
        raise UnprocessableEntityError("amount must be greater than 0")
    await _validate_references(
        db,
        organization_id=organization_id,
        client_id=client_id,
        project_id=project_id,
        invoice_id=invoice_id,
    )

    org_session = OrgSession(db, organization_id=organization_id)
    income = Income(
        id=uuid7(),
        amount=amount,
        currency=currency,
        source=source,
        client_id=client_id,
        project_id=project_id,
        invoice_id=invoice_id,
        received_on=received_on,
        payment_method=payment_method,
        reference=reference,
        notes=notes,
        created_by=actor.user_id,
    )
    org_session.add(income)
    await record(
        db,
        organization_id=organization_id,
        event="income.created",
        entity_type="income",
        entity_id=income.id,
        actor_id=actor.user_id,
        metadata={"source": income.source, "amount": str(income.amount)},
    )
    await db.commit()
    return income


async def list_income(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    actor: Membership,
    limit: int = 50,
    offset: int = 0,
) -> IncomeList:
    ensure_actor_in_org(actor, organization_id)

    total_result = await db.execute(
        select(func.count()).select_from(Income).where(Income.organization_id == organization_id)
    )
    total = total_result.scalar_one()

    org_session = OrgSession(db, organization_id=organization_id)
    result = await db.execute(
        org_session.select(Income)
        .order_by(Income.received_on.desc(), Income.id.asc())
        .limit(limit)
        .offset(offset)
    )
    return IncomeList(items=list(result.scalars().all()), total=total)


async def get_income(
    db: AsyncSession, *, organization_id: uuid.UUID, actor: Membership, income_id: uuid.UUID
) -> Income:
    ensure_actor_in_org(actor, organization_id)
    return await get_income_in_org(db, organization_id=organization_id, income_id=income_id)


async def update_income(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    actor: Membership,
    income_id: uuid.UUID,
    updates: dict[str, Any],
) -> Income:
    ensure_actor_in_org(actor, organization_id)
    income = await get_income_in_org(db, organization_id=organization_id, income_id=income_id)

    if "amount" in updates and updates["amount"] <= 0:
        raise UnprocessableEntityError("amount must be greater than 0")
    await _validate_references(
        db,
        organization_id=organization_id,
        client_id=updates.get("client_id", income.client_id),
        project_id=updates.get("project_id", income.project_id),
        invoice_id=updates.get("invoice_id", income.invoice_id),
    )

    for field, value in updates.items():
        setattr(income, field, value)

    await db.commit()
    return await get_income_in_org(db, organization_id=organization_id, income_id=income_id)


async def delete_income(
    db: AsyncSession, *, organization_id: uuid.UUID, actor: Membership, income_id: uuid.UUID
) -> None:
    """ADR-0011: income is not one of the four soft-deleted entities — a
    hard delete, with the deletion recorded as an audit event (same
    reasoning as meeting_service.delete_meeting)."""
    ensure_actor_in_org(actor, organization_id)
    income = await get_income_in_org(db, organization_id=organization_id, income_id=income_id)

    await record(
        db,
        organization_id=organization_id,
        event="income.deleted",
        entity_type="income",
        entity_id=income.id,
        actor_id=actor.user_id,
        metadata={"source": income.source},
        audit=True,
    )
    await db.delete(income)
    await db.commit()

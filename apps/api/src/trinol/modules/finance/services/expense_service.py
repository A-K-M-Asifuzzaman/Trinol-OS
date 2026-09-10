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
from trinol.modules.finance.models import Expense, ExpenseCategory
from trinol.modules.identity.models import Membership
from trinol.platform.activity import record
from trinol.platform.file_storage.protocol import FileStorage
from trinol.platform.files import create_file_object
from trinol.platform.models import FileObject


@dataclass(frozen=True, slots=True)
class ExpenseList:
    items: list[Expense]
    total: int


@dataclass(frozen=True, slots=True)
class ExpenseReceiptDownload:
    file_object: FileObject
    data: bytes


def ensure_actor_in_org(actor: Membership, organization_id: uuid.UUID) -> None:
    """Defense in depth, same reasoning as every other module's own copy of
    this check (e.g. income_service's own copy)."""
    if actor.organization_id != organization_id:
        raise ForbiddenError("Actor does not belong to this organization")


async def get_expense_in_org(
    db: AsyncSession, *, organization_id: uuid.UUID, expense_id: uuid.UUID
) -> Expense:
    """Org-scoped lookup — 404s a cross-org id exactly like a missing one
    (RBAC.md §4), same pattern as income_service.get_income_in_org."""
    result = await db.execute(
        select(Expense)
        .where(Expense.organization_id == organization_id, Expense.id == expense_id)
        .execution_options(populate_existing=True)
    )
    expense = result.scalar_one_or_none()
    if expense is None:
        raise NotFoundError("Expense not found")
    return expense


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


async def create_expense(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    actor: Membership,
    amount: Any,
    currency: str,
    category: ExpenseCategory,
    description: str,
    vendor: str | None,
    spent_on: date,
    payment_method: str,
    notes: str | None,
) -> Expense:
    # RBAC.md §2: "Income/expenses: write" is ADMIN+-tier, flat — the
    # route's own require(Permission.FINANCE_WRITE) is the entire
    # authorization check (ROADMAP.md Phase 5 decision 2), same reasoning
    # as income_service.create_income.
    ensure_actor_in_org(actor, organization_id)
    if amount <= 0:
        # Mirrors ck_expense_amount_positive at the application layer too,
        # same reasoning as create_income's own check.
        raise UnprocessableEntityError("amount must be greater than 0")

    org_session = OrgSession(db, organization_id=organization_id)
    expense = Expense(
        id=uuid7(),
        amount=amount,
        currency=currency,
        category=category,
        description=description,
        vendor=vendor,
        spent_on=spent_on,
        payment_method=payment_method,
        notes=notes,
        created_by=actor.user_id,
    )
    org_session.add(expense)
    await record(
        db,
        organization_id=organization_id,
        event="expense.created",
        entity_type="expense",
        entity_id=expense.id,
        actor_id=actor.user_id,
        metadata={"category": expense.category.value, "amount": str(expense.amount)},
    )
    await db.commit()
    return expense


async def list_expenses(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    actor: Membership,
    limit: int = 50,
    offset: int = 0,
) -> ExpenseList:
    ensure_actor_in_org(actor, organization_id)

    total_result = await db.execute(
        select(func.count()).select_from(Expense).where(Expense.organization_id == organization_id)
    )
    total = total_result.scalar_one()

    org_session = OrgSession(db, organization_id=organization_id)
    result = await db.execute(
        org_session.select(Expense)
        .order_by(Expense.spent_on.desc(), Expense.id.asc())
        .limit(limit)
        .offset(offset)
    )
    return ExpenseList(items=list(result.scalars().all()), total=total)


async def get_expense(
    db: AsyncSession, *, organization_id: uuid.UUID, actor: Membership, expense_id: uuid.UUID
) -> Expense:
    ensure_actor_in_org(actor, organization_id)
    return await get_expense_in_org(db, organization_id=organization_id, expense_id=expense_id)


async def update_expense(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    actor: Membership,
    expense_id: uuid.UUID,
    updates: dict[str, Any],
) -> Expense:
    ensure_actor_in_org(actor, organization_id)
    expense = await get_expense_in_org(db, organization_id=organization_id, expense_id=expense_id)

    if "amount" in updates and updates["amount"] <= 0:
        raise UnprocessableEntityError("amount must be greater than 0")

    for field, value in updates.items():
        setattr(expense, field, value)

    await db.commit()
    return await get_expense_in_org(db, organization_id=organization_id, expense_id=expense_id)


async def _clear_receipt(
    db: AsyncSession, *, organization_id: uuid.UUID, expense: Expense
) -> str | None:
    """Nulls `receipt_file_id` and deletes the file_objects row, returning
    its storage_key for the caller to delete *after* its own `db.commit()`
    — never before. Mirrors task_attachment_service.delete_attachment's
    own ordering discipline exactly: deleting the blob before the
    surrounding transaction commits risks a rollback leaving a DB row that
    references an already-deleted blob (a dangling reference), which is
    worse than the alternative (a blob briefly orphaned with no DB
    reference) if a failure happens between commit and the actual
    `storage.delete` call."""
    if expense.receipt_file_id is None:
        return None
    old_file_object = await _get_file_object_in_org(
        db, organization_id=organization_id, file_id=expense.receipt_file_id
    )
    storage_key = old_file_object.storage_key
    expense.receipt_file_id = None
    await db.flush()
    await db.delete(old_file_object)
    await db.flush()
    return storage_key


async def upload_receipt(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    actor: Membership,
    expense_id: uuid.UUID,
    filename: str,
    data: bytes,
    storage: FileStorage,
) -> Expense:
    """Uploading again replaces the existing receipt rather than adding a
    second one (expenses.receipt_file_id is a single nullable column, not
    a list like task_attachments). Writing the *new* blob before commit is
    safe (an uncommitted row pointing nowhere is a harmless no-op on
    rollback, same as create_attachment's own ordering); deleting the
    *old* blob is deferred until after commit, per _clear_receipt."""
    ensure_actor_in_org(actor, organization_id)
    expense = await get_expense_in_org(db, organization_id=organization_id, expense_id=expense_id)
    old_storage_key = await _clear_receipt(db, organization_id=organization_id, expense=expense)

    file_object = await create_file_object(
        db,
        organization_id=organization_id,
        uploaded_by=actor.user_id,
        filename=filename,
        data=data,
        storage=storage,
    )
    expense.receipt_file_id = file_object.id
    await db.commit()
    if old_storage_key is not None:
        await storage.delete(old_storage_key)
    return await get_expense_in_org(db, organization_id=organization_id, expense_id=expense_id)


async def download_receipt(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    actor: Membership,
    expense_id: uuid.UUID,
    storage: FileStorage,
) -> ExpenseReceiptDownload:
    """Authorized by FINANCE_READ alone (route-level), no separate
    per-receipt permission — same reasoning as task attachments' download
    (ADR-0008): reading an expense implies reading its own receipt."""
    ensure_actor_in_org(actor, organization_id)
    expense = await get_expense_in_org(db, organization_id=organization_id, expense_id=expense_id)
    if expense.receipt_file_id is None:
        raise NotFoundError("This expense has no receipt")
    file_object = await _get_file_object_in_org(
        db, organization_id=organization_id, file_id=expense.receipt_file_id
    )
    data = await storage.get(file_object.storage_key)
    return ExpenseReceiptDownload(file_object=file_object, data=data)


async def delete_receipt(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    actor: Membership,
    expense_id: uuid.UUID,
    storage: FileStorage,
) -> None:
    ensure_actor_in_org(actor, organization_id)
    expense = await get_expense_in_org(db, organization_id=organization_id, expense_id=expense_id)
    if expense.receipt_file_id is None:
        raise NotFoundError("This expense has no receipt")
    old_storage_key = await _clear_receipt(db, organization_id=organization_id, expense=expense)
    await db.commit()
    if old_storage_key is not None:
        await storage.delete(old_storage_key)


async def delete_expense(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    actor: Membership,
    expense_id: uuid.UUID,
    storage: FileStorage,
) -> None:
    """ADR-0011: expenses are not one of the four soft-deleted entities —
    a hard delete, with the deletion recorded as an audit event (same
    reasoning as income_service.delete_income). A receipt, if any, is
    cleared and deleted first (same combined-delete discipline as
    _clear_receipt) so nothing in file_objects is orphaned."""
    ensure_actor_in_org(actor, organization_id)
    expense = await get_expense_in_org(db, organization_id=organization_id, expense_id=expense_id)
    old_storage_key = await _clear_receipt(db, organization_id=organization_id, expense=expense)

    await record(
        db,
        organization_id=organization_id,
        event="expense.deleted",
        entity_type="expense",
        entity_id=expense.id,
        actor_id=actor.user_id,
        metadata={"category": expense.category.value},
        audit=True,
    )
    await db.delete(expense)
    await db.commit()
    if old_storage_key is not None:
        await storage.delete(old_storage_key)

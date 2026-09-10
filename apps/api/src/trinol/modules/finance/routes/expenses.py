from __future__ import annotations

import re
import uuid
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Query, UploadFile
from fastapi import Response as FastAPIResponse
from sqlalchemy.ext.asyncio import AsyncSession

from trinol.core.authz.permissions import Permission
from trinol.core.authz.require import require
from trinol.core.db.engine import get_db_session
from trinol.modules.finance.models import Expense
from trinol.modules.finance.schemas import (
    ExpenseCreateRequest,
    ExpenseListResponse,
    ExpenseResponse,
    ExpenseUpdateRequest,
)
from trinol.modules.finance.services.expense_service import (
    create_expense,
    delete_expense,
    delete_receipt,
    download_receipt,
    get_expense,
    list_expenses,
    update_expense,
    upload_receipt,
)
from trinol.modules.identity.deps import get_current_membership
from trinol.modules.identity.models import Membership
from trinol.platform.file_storage.deps import get_file_storage
from trinol.platform.file_storage.protocol import FileStorage

router = APIRouter(prefix="/api/v1/finance/expenses", tags=["finance"])


def expense_to_response(expense: Expense) -> ExpenseResponse:
    return ExpenseResponse(
        id=expense.id,
        amount=expense.amount,
        currency=expense.currency,
        category=expense.category,
        description=expense.description,
        vendor=expense.vendor,
        spent_on=expense.spent_on,
        payment_method=expense.payment_method,
        receipt_file_id=expense.receipt_file_id,
        notes=expense.notes,
        created_by=expense.created_by,
        created_at=expense.created_at,
        updated_at=expense.updated_at,
    )


@router.post(
    "",
    response_model=ExpenseResponse,
    status_code=201,
    dependencies=[Depends(require(Permission.FINANCE_WRITE))],
)
async def create_expense_route(
    payload: ExpenseCreateRequest,
    membership: Membership = Depends(get_current_membership),
    db: AsyncSession = Depends(get_db_session),
) -> ExpenseResponse:
    expense = await create_expense(
        db,
        organization_id=membership.organization_id,
        actor=membership,
        amount=payload.amount,
        currency=payload.currency,
        category=payload.category,
        description=payload.description,
        vendor=payload.vendor,
        spent_on=payload.spent_on,
        payment_method=payload.payment_method,
        notes=payload.notes,
    )
    return expense_to_response(expense)


@router.get(
    "",
    response_model=ExpenseListResponse,
    dependencies=[Depends(require(Permission.FINANCE_READ))],
)
async def list_expenses_route(
    limit: int = Query(default=50, ge=1, le=200),  # ADR-0005: default 50, hard cap 200
    offset: int = Query(default=0, ge=0),
    membership: Membership = Depends(get_current_membership),
    db: AsyncSession = Depends(get_db_session),
) -> ExpenseListResponse:
    result = await list_expenses(
        db, organization_id=membership.organization_id, actor=membership, limit=limit, offset=offset
    )
    return ExpenseListResponse(
        items=[expense_to_response(e) for e in result.items], total=result.total
    )


@router.get(
    "/{expense_id}",
    response_model=ExpenseResponse,
    dependencies=[Depends(require(Permission.FINANCE_READ))],
)
async def get_expense_route(
    expense_id: uuid.UUID,
    membership: Membership = Depends(get_current_membership),
    db: AsyncSession = Depends(get_db_session),
) -> ExpenseResponse:
    expense = await get_expense(
        db, organization_id=membership.organization_id, actor=membership, expense_id=expense_id
    )
    return expense_to_response(expense)


@router.patch(
    "/{expense_id}",
    response_model=ExpenseResponse,
    dependencies=[Depends(require(Permission.FINANCE_WRITE))],
)
async def update_expense_route(
    expense_id: uuid.UUID,
    payload: ExpenseUpdateRequest,
    membership: Membership = Depends(get_current_membership),
    db: AsyncSession = Depends(get_db_session),
) -> ExpenseResponse:
    updates = payload.model_dump(exclude_unset=True)
    expense = await update_expense(
        db,
        organization_id=membership.organization_id,
        actor=membership,
        expense_id=expense_id,
        updates=updates,
    )
    return expense_to_response(expense)


@router.delete(
    "/{expense_id}",
    status_code=204,
    dependencies=[Depends(require(Permission.FINANCE_WRITE))],
)
async def delete_expense_route(
    expense_id: uuid.UUID,
    membership: Membership = Depends(get_current_membership),
    db: AsyncSession = Depends(get_db_session),
    storage: FileStorage = Depends(get_file_storage),
) -> None:
    await delete_expense(
        db,
        organization_id=membership.organization_id,
        actor=membership,
        expense_id=expense_id,
        storage=storage,
    )


@router.post(
    "/{expense_id}/receipt",
    response_model=ExpenseResponse,
    status_code=201,
    dependencies=[Depends(require(Permission.FINANCE_WRITE))],
)
async def upload_receipt_route(
    expense_id: uuid.UUID,
    file: UploadFile = File(...),
    membership: Membership = Depends(get_current_membership),
    db: AsyncSession = Depends(get_db_session),
    storage: FileStorage = Depends(get_file_storage),
) -> ExpenseResponse:
    data = await file.read()
    expense = await upload_receipt(
        db,
        organization_id=membership.organization_id,
        actor=membership,
        expense_id=expense_id,
        filename=file.filename or "upload",
        data=data,
        storage=storage,
    )
    return expense_to_response(expense)


def _content_disposition(filename: str) -> str:
    """Same encoding as work.routes.tasks._content_disposition — RFC 6266's
    `filename*` form percent-encodes the entire name so a filename
    containing `"`, `\\`, or a raw control byte can't break out of the
    header, with a stripped-down ASCII fallback for older clients."""
    ascii_fallback = re.sub(r"[^A-Za-z0-9 ._-]", "_", filename).strip() or "download"
    encoded = quote(filename, safe="")
    return f"attachment; filename=\"{ascii_fallback}\"; filename*=UTF-8''{encoded}"


@router.get(
    "/{expense_id}/receipt",
    dependencies=[Depends(require(Permission.FINANCE_READ))],
)
async def download_receipt_route(
    expense_id: uuid.UUID,
    membership: Membership = Depends(get_current_membership),
    db: AsyncSession = Depends(get_db_session),
    storage: FileStorage = Depends(get_file_storage),
) -> FastAPIResponse:
    # SECURITY.md §6: authorized download, streamed with an attachment
    # disposition and nosniff — no public bucket, no guessable direct URL.
    download = await download_receipt(
        db,
        organization_id=membership.organization_id,
        actor=membership,
        expense_id=expense_id,
        storage=storage,
    )
    return FastAPIResponse(
        content=download.data,
        media_type=download.file_object.content_type,
        headers={
            "Content-Disposition": _content_disposition(download.file_object.filename),
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.delete(
    "/{expense_id}/receipt",
    status_code=204,
    dependencies=[Depends(require(Permission.FINANCE_WRITE))],
)
async def delete_receipt_route(
    expense_id: uuid.UUID,
    membership: Membership = Depends(get_current_membership),
    db: AsyncSession = Depends(get_db_session),
    storage: FileStorage = Depends(get_file_storage),
) -> None:
    await delete_receipt(
        db,
        organization_id=membership.organization_id,
        actor=membership,
        expense_id=expense_id,
        storage=storage,
    )

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from trinol.modules.work.schemas import BudgetDecimal

# finance -> work is an allowed import direction (ARCHITECTURE.md §3), unlike
# crm -> work (which duplicates its own decimal validator instead) — reusing
# BudgetDecimal directly here is correct, not an oversight.


class IncomeCreateRequest(BaseModel):
    amount: BudgetDecimal
    currency: str = Field(default="USD", min_length=3, max_length=3)
    source: str = Field(min_length=1, max_length=200)
    client_id: uuid.UUID | None = None
    project_id: uuid.UUID | None = None
    invoice_id: uuid.UUID | None = None
    received_on: date
    payment_method: str = Field(min_length=1, max_length=100)
    reference: str | None = Field(default=None, max_length=200)
    notes: str | None = Field(default=None, max_length=4000)


class IncomeUpdateRequest(BaseModel):
    """Partial update: only fields present in the request body are applied
    (routes/income.py uses `model_dump(exclude_unset=True)`)."""

    amount: BudgetDecimal | None = None
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    source: str | None = Field(default=None, min_length=1, max_length=200)
    client_id: uuid.UUID | None = None
    project_id: uuid.UUID | None = None
    invoice_id: uuid.UUID | None = None
    received_on: date | None = None
    payment_method: str | None = Field(default=None, min_length=1, max_length=100)
    reference: str | None = Field(default=None, max_length=200)
    notes: str | None = Field(default=None, max_length=4000)


class IncomeResponse(BaseModel):
    """`amount` is a plain `Decimal`, not `BudgetDecimal` — that alias's
    `BeforeValidator` only accepts a decimal *string* (request-side
    parsing); a response is built from an ORM row's real `Decimal` value,
    which the validator would reject, same reasoning as
    `ProjectResponse.budget` upstream."""

    id: uuid.UUID
    amount: Decimal
    currency: str
    source: str
    client_id: uuid.UUID | None
    project_id: uuid.UUID | None
    invoice_id: uuid.UUID | None
    received_on: date
    payment_method: str
    reference: str | None
    notes: str | None
    created_by: uuid.UUID
    created_at: datetime
    updated_at: datetime


class IncomeListResponse(BaseModel):
    """ADR-0005: every list endpoint returns {items, total}, never a bare
    array."""

    items: list[IncomeResponse]
    total: int

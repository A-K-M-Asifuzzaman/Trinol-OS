from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field, model_validator

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

    @model_validator(mode="after")
    def _no_null_for_required_fields(self) -> IncomeUpdateRequest:
        """Same pattern as `ProjectUpdateRequest`/`TaskUpdateRequest`:
        `exclude_unset=True` already lets an *omitted* field pass through
        untouched, but an *explicit* `null` for one of `income`'s five
        NOT NULL columns would otherwise reach `income_service.
        update_income` as `None` and either blow up on the `amount <= 0`
        comparison (`TypeError`) or hit the DB's NOT NULL constraint as an
        unhandled 500 — caught by Codex review, not by the original test
        suite. `client_id`/`project_id`/`invoice_id` are genuinely
        nullable columns and are deliberately excluded here."""
        for field in ("amount", "currency", "source", "received_on", "payment_method"):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} may not be null")
        return self


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

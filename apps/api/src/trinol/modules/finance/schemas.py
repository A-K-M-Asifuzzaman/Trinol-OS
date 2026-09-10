from __future__ import annotations

import re
import uuid
from datetime import date, datetime
from decimal import Decimal
from functools import partial
from typing import Annotated, Any

from pydantic import BaseModel, BeforeValidator, Field, WithJsonSchema, model_validator

from trinol.modules.finance.models import ExpenseCategory, InvoiceStatus
from trinol.modules.work.schemas import BudgetDecimal

# finance -> work is an allowed import direction (ARCHITECTURE.md §3), unlike
# crm -> work (which duplicates its own decimal validator instead) — reusing
# BudgetDecimal directly here is correct, not an oversight.


def _validate_decimal_string(pattern: str, error: str, value: Any) -> Any:
    """Duplicated from work.schemas's private copy rather than imported —
    it's an underscore-prefixed helper, not part of that module's public
    surface, same reasoning crm/schemas.py already gives for its own copy
    even though (unlike crm) finance -> work import is allowed."""
    if not isinstance(value, str) or re.fullmatch(pattern, value) is None:
        raise ValueError(error)
    return value


# NUMERIC(12,3): at most 9 integer digits, 1-3 decimal digits. Non-negative
# — a line item can't have a negative quantity (unlike BudgetDecimal, which
# stays general-purpose and allows one).
_QUANTITY_PATTERN = r"^(?:0|[1-9]\d{0,8})(?:\.\d{1,3})?$"
QuantityDecimal = Annotated[
    Decimal,
    BeforeValidator(
        partial(
            _validate_decimal_string,
            _QUANTITY_PATTERN,
            "quantity must be a non-negative decimal string with at most 9 integer "
            "and 3 decimal digits",
        )
    ),
    WithJsonSchema({"type": "string", "pattern": _QUANTITY_PATTERN}, mode="validation"),
]


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


class ExpenseCreateRequest(BaseModel):
    """No `receipt_file_id` here — a receipt is attached via the dedicated
    `POST /finance/expenses/{expense_id}/receipt` multipart route, same
    two-step shape as task attachments (create the JSON resource, then
    attach the file)."""

    amount: BudgetDecimal
    currency: str = Field(default="USD", min_length=3, max_length=3)
    category: ExpenseCategory
    description: str = Field(min_length=1, max_length=2000)
    vendor: str | None = Field(default=None, max_length=200)
    spent_on: date
    payment_method: str = Field(min_length=1, max_length=100)
    notes: str | None = Field(default=None, max_length=4000)


class ExpenseUpdateRequest(BaseModel):
    """Partial update: only fields present in the request body are applied
    (routes/expenses.py uses `model_dump(exclude_unset=True)`). No
    `receipt_file_id` here either — managed only by the dedicated
    upload/delete-receipt routes, never by a plain PATCH."""

    amount: BudgetDecimal | None = None
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    category: ExpenseCategory | None = None
    description: str | None = Field(default=None, min_length=1, max_length=2000)
    vendor: str | None = Field(default=None, max_length=200)
    spent_on: date | None = None
    payment_method: str | None = Field(default=None, min_length=1, max_length=100)
    notes: str | None = Field(default=None, max_length=4000)

    @model_validator(mode="after")
    def _no_null_for_required_fields(self) -> ExpenseUpdateRequest:
        """Same guard as `IncomeUpdateRequest` (Codex Stage 2 finding,
        applied proactively here rather than reactively) — `vendor`/
        `notes` are genuinely nullable and deliberately excluded."""
        required_fields = (
            "amount",
            "currency",
            "category",
            "description",
            "spent_on",
            "payment_method",
        )
        for field in required_fields:
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} may not be null")
        return self


class ExpenseResponse(BaseModel):
    """`amount` is a plain `Decimal`, not `BudgetDecimal` — same reasoning
    as `IncomeResponse.amount`."""

    id: uuid.UUID
    amount: Decimal
    currency: str
    category: ExpenseCategory
    description: str
    vendor: str | None
    spent_on: date
    payment_method: str
    receipt_file_id: uuid.UUID | None
    notes: str | None
    created_by: uuid.UUID
    created_at: datetime
    updated_at: datetime


class ExpenseListResponse(BaseModel):
    items: list[ExpenseResponse]
    total: int


class InvoiceLineItemInput(BaseModel):
    """Client-supplied line item shape for create/update — `line_total` is
    never accepted from the client (ADR-0007: totals are computed by the
    backend, always); `invoice_service.py` derives it from `quantity *
    unit_price`, rounded once per line."""

    description: str = Field(min_length=1, max_length=500)
    quantity: QuantityDecimal
    unit_price: BudgetDecimal


class InvoiceItemResponse(BaseModel):
    id: uuid.UUID
    description: str
    quantity: Decimal
    unit_price: Decimal
    line_total: Decimal
    position: int


class InvoiceCreateRequest(BaseModel):
    client_id: uuid.UUID
    project_id: uuid.UUID | None = None
    issue_date: date
    due_date: date
    currency: str = Field(default="USD", min_length=3, max_length=3)
    items: list[InvoiceLineItemInput] = Field(min_length=1)
    # Flat currency amounts, not a tax/discount *rate* — ROADMAP.md's own
    # settled decision: "one rate per invoice is assumed; per-line tax and
    # VAT/GST numbers are not built." Whoever fills out the invoice enters
    # the resulting dollar figure directly.
    discount_amount: BudgetDecimal = Decimal("0")
    tax_amount: BudgetDecimal = Decimal("0")
    notes: str | None = Field(default=None, max_length=4000)
    terms: str | None = Field(default=None, max_length=4000)


class InvoiceUpdateRequest(BaseModel):
    """Partial update: only fields present in the request body are applied
    (routes/invoices.py uses `model_dump(exclude_unset=True)`).
    `invoice_service.update_invoice` rejects this outright once the
    invoice has left `DRAFT` (ADR-0007 immutability). `items`, when
    present, wholesale-replaces the existing line items — there is no
    separate add/remove/reorder sub-resource, matching how small an
    invoice's own item list is expected to stay (MASTER_PROMPT §20 lists
    `items` as a plain top-level invoice field, not its own routes)."""

    client_id: uuid.UUID | None = None
    project_id: uuid.UUID | None = None
    issue_date: date | None = None
    due_date: date | None = None
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    items: list[InvoiceLineItemInput] | None = Field(default=None, min_length=1)
    discount_amount: BudgetDecimal | None = None
    tax_amount: BudgetDecimal | None = None
    notes: str | None = Field(default=None, max_length=4000)
    terms: str | None = Field(default=None, max_length=4000)

    @model_validator(mode="after")
    def _no_null_for_required_fields(self) -> InvoiceUpdateRequest:
        """Same guard as Income/ExpenseUpdateRequest — `project_id`/
        `notes`/`terms` are genuinely nullable and deliberately excluded."""
        required_fields = (
            "client_id",
            "issue_date",
            "due_date",
            "currency",
            "items",
            "discount_amount",
            "tax_amount",
        )
        for field in required_fields:
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} may not be null")
        return self


class InvoiceResponse(BaseModel):
    """`is_overdue` is derived by the route mapper from `status`/`due_date`
    at read time (ADR-0007) — never a stored column, never a client input.
    `subtotal`/`discount_amount`/`tax_amount`/`total`/`amount_paid` are all
    plain `Decimal`, not `BudgetDecimal` — same reasoning as `IncomeResponse
    .amount`."""

    id: uuid.UUID
    invoice_number: str
    client_id: uuid.UUID
    project_id: uuid.UUID | None
    issue_date: date
    due_date: date
    currency: str
    items: list[InvoiceItemResponse]
    subtotal: Decimal
    discount_amount: Decimal
    tax_amount: Decimal
    total: Decimal
    amount_paid: Decimal
    status: InvoiceStatus
    is_overdue: bool
    notes: str | None
    terms: str | None
    sent_at: datetime | None
    created_by: uuid.UUID
    created_at: datetime
    updated_at: datetime


class InvoiceListResponse(BaseModel):
    items: list[InvoiceResponse]
    total: int


class PaymentCreateRequest(BaseModel):
    """Append-only (ADR-0007) — there is no `PaymentUpdateRequest`; a
    payment, once recorded, is never edited or deleted."""

    amount: BudgetDecimal
    currency: str = Field(default="USD", min_length=3, max_length=3)
    paid_on: date
    method: str = Field(min_length=1, max_length=100)
    reference: str | None = Field(default=None, max_length=200)


class PaymentResponse(BaseModel):
    """`amount` is a plain `Decimal`, not `BudgetDecimal` — same reasoning
    as `IncomeResponse.amount`."""

    id: uuid.UUID
    invoice_id: uuid.UUID
    amount: Decimal
    currency: str
    paid_on: date
    method: str
    reference: str | None
    recorded_by: uuid.UUID
    created_at: datetime


class PaymentListResponse(BaseModel):
    items: list[PaymentResponse]
    total: int

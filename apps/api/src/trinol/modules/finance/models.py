from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

import sqlalchemy as sa
from sqlalchemy import (
    CheckConstraint,
    FetchedValue,
    ForeignKeyConstraint,
    Index,
    PrimaryKeyConstraint,
    UniqueConstraint,
    text,
)
from sqlalchemy import Enum as PgEnum
from sqlalchemy.orm import Mapped, mapped_column

from trinol.core.db.base import Base
from trinol.core.db.org_scoped import OrgScoped
from trinol.core.ids import uuid7

_TZ = sa.DateTime(timezone=True)
_MONEY = sa.Numeric(14, 2)


class ExpenseCategory(StrEnum):
    """MASTER_PROMPT §19's 10-value category list."""

    HOSTING = "HOSTING"
    DOMAINS = "DOMAINS"
    SOFTWARE = "SOFTWARE"
    MARKETING = "MARKETING"
    SALARY = "SALARY"
    CONTRACTOR = "CONTRACTOR"
    OFFICE = "OFFICE"
    TRAVEL = "TRAVEL"
    EQUIPMENT = "EQUIPMENT"
    OTHER = "OTHER"


class InvoiceStatus(StrEnum):
    """DATABASE.md §3 / ADR-0007: 5 stored values only. `OVERDUE` (in
    MASTER_PROMPT §20's stale 6-value list) is derived on read from
    `status IN (SENT, PARTIALLY_PAID) AND due_date < today`, never stored."""

    DRAFT = "DRAFT"
    SENT = "SENT"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    CANCELLED = "CANCELLED"


class Income(OrgScoped, Base):
    """DATABASE.md §3 (finance). `invoice_id` is a plain optional cross-
    reference (ARCHITECTURE.md §3) — recording a payment does not write an
    income row automatically; that link is user-entered."""

    __tablename__ = "income"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    amount: Mapped[Decimal] = mapped_column(_MONEY, nullable=False)
    currency: Mapped[str] = mapped_column(sa.Text, nullable=False, server_default="USD")
    source: Mapped[str] = mapped_column(sa.Text, nullable=False)
    client_id: Mapped[uuid.UUID | None] = mapped_column(default=None)
    project_id: Mapped[uuid.UUID | None] = mapped_column(default=None)
    invoice_id: Mapped[uuid.UUID | None] = mapped_column(default=None)
    received_on: Mapped[date] = mapped_column(sa.Date, nullable=False)
    payment_method: Mapped[str] = mapped_column(sa.Text, nullable=False)
    reference: Mapped[str | None] = mapped_column(sa.Text, default=None)
    notes: Mapped[str | None] = mapped_column(sa.Text, default=None)
    # Person reference -> memberships, not users (DATABASE.md §5.1).
    created_by: Mapped[uuid.UUID] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(_TZ, server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(
        _TZ, server_default=text("now()"), server_onupdate=FetchedValue()
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "client_id"],
            ["clients.organization_id", "clients.id"],
            name="fk_income_org_client_clients",
            # Nullable; clients are soft-deleted only (ADR-0011) — same
            # reasoning as meetings.client_id.
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["organization_id", "project_id"],
            ["projects.organization_id", "projects.id"],
            name="fk_income_org_project_projects",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["organization_id", "invoice_id"],
            ["invoices.organization_id", "invoices.id"],
            name="fk_income_org_invoice_invoices",
            # Nullable; invoices are cancelled, never deleted (ADR-0007) —
            # RESTRICT is defensive, this path should never fire.
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["organization_id", "created_by"],
            ["memberships.organization_id", "memberships.user_id"],
            name="fk_income_org_created_by_memberships",
            ondelete="RESTRICT",
        ),
        # Not spelled out in DATABASE.md's finance section, but mirrors
        # ck_payment_positive's own reasoning: a negative income row is a
        # data-entry error, not a legitimate state.
        CheckConstraint("amount > 0", name="ck_income_amount_positive"),
        Index("ix_income_org_received_on", "organization_id", "received_on"),
        Index("ix_income_org_client", "organization_id", "client_id"),
        Index("ix_income_org_project", "organization_id", "project_id"),
        Index("ix_income_org_invoice", "organization_id", "invoice_id"),
        Index("ix_income_org_created_by", "organization_id", "created_by"),
    )


class Expense(OrgScoped, Base):
    __tablename__ = "expenses"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    amount: Mapped[Decimal] = mapped_column(_MONEY, nullable=False)
    currency: Mapped[str] = mapped_column(sa.Text, nullable=False, server_default="USD")
    category: Mapped[ExpenseCategory] = mapped_column(
        PgEnum(
            ExpenseCategory,
            name="expense_category",
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
    )
    description: Mapped[str] = mapped_column(sa.Text, nullable=False)
    vendor: Mapped[str | None] = mapped_column(sa.Text, default=None)
    spent_on: Mapped[date] = mapped_column(sa.Date, nullable=False)
    payment_method: Mapped[str] = mapped_column(sa.Text, nullable=False)
    receipt_file_id: Mapped[uuid.UUID | None] = mapped_column(default=None)
    notes: Mapped[str | None] = mapped_column(sa.Text, default=None)
    created_by: Mapped[uuid.UUID] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(_TZ, server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(
        _TZ, server_default=text("now()"), server_onupdate=FetchedValue()
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "receipt_file_id"],
            ["file_objects.organization_id", "file_objects.id"],
            name="fk_expenses_org_receipt_file_objects",
            # Same RESTRICT reasoning as task_attachments.file_id: nothing
            # deletes a file_objects row out from under an expense.
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["organization_id", "created_by"],
            ["memberships.organization_id", "memberships.user_id"],
            name="fk_expenses_org_created_by_memberships",
            ondelete="RESTRICT",
        ),
        CheckConstraint("amount > 0", name="ck_expense_amount_positive"),
        Index("ix_expenses_org_spent_on", "organization_id", "spent_on"),
        Index("ix_expenses_org_category", "organization_id", "category"),
        Index("ix_expenses_org_receipt", "organization_id", "receipt_file_id"),
        Index("ix_expenses_org_created_by", "organization_id", "created_by"),
    )


class Invoice(OrgScoped, Base):
    """DATABASE.md §3 / ADR-0007. One of the four `archived_at` entities
    (ADR-0011) — but the ADR's own reason is that an invoice is cancelled,
    never deleted, so no route sets `archived_at` in V1 (ROADMAP.md Phase 5
    decision); it exists only as the composite-FK-target column and a
    defensive list-query filter."""

    __tablename__ = "invoices"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    invoice_number: Mapped[str] = mapped_column(sa.Text, nullable=False)
    client_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    project_id: Mapped[uuid.UUID | None] = mapped_column(default=None)
    issue_date: Mapped[date] = mapped_column(sa.Date, nullable=False)
    due_date: Mapped[date] = mapped_column(sa.Date, nullable=False)
    currency: Mapped[str] = mapped_column(sa.Text, nullable=False, server_default="USD")
    subtotal: Mapped[Decimal] = mapped_column(_MONEY, nullable=False)
    discount_amount: Mapped[Decimal] = mapped_column(_MONEY, nullable=False, server_default="0")
    tax_amount: Mapped[Decimal] = mapped_column(_MONEY, nullable=False, server_default="0")
    total: Mapped[Decimal] = mapped_column(_MONEY, nullable=False)
    amount_paid: Mapped[Decimal] = mapped_column(_MONEY, nullable=False, server_default="0")
    status: Mapped[InvoiceStatus] = mapped_column(
        PgEnum(
            InvoiceStatus,
            name="invoice_status",
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        server_default=InvoiceStatus.DRAFT.value,
    )
    notes: Mapped[str | None] = mapped_column(sa.Text, default=None)
    terms: Mapped[str | None] = mapped_column(sa.Text, default=None)
    sent_at: Mapped[datetime | None] = mapped_column(_TZ, default=None)
    created_by: Mapped[uuid.UUID] = mapped_column(nullable=False)
    archived_at: Mapped[datetime | None] = mapped_column(_TZ, default=None)
    created_at: Mapped[datetime] = mapped_column(_TZ, server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(
        _TZ, server_default=text("now()"), server_onupdate=FetchedValue()
    )

    __table_args__ = (
        # The hard guarantee against duplicate numbers (ADR-0007) — the
        # row-locked counter (InvoiceCounter) is what keeps two concurrent
        # requests from ever computing the same number in the first place.
        UniqueConstraint("organization_id", "invoice_number", name="uq_invoice_org_number"),
        # Required by composite FKs from invoice_items, payments,
        # income.invoice_id (DATABASE.md §5.1).
        UniqueConstraint("organization_id", "id", name="uq_invoices_org_id"),
        ForeignKeyConstraint(
            ["organization_id", "client_id"],
            ["clients.organization_id", "clients.id"],
            name="fk_invoices_org_client_clients",
            # Non-nullable; clients are soft-deleted only (ADR-0011).
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["organization_id", "project_id"],
            ["projects.organization_id", "projects.id"],
            name="fk_invoices_org_project_projects",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["organization_id", "created_by"],
            ["memberships.organization_id", "memberships.user_id"],
            name="fk_invoices_org_created_by_memberships",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "subtotal >= 0 AND discount_amount >= 0 AND tax_amount >= 0 "
            "AND total >= 0 AND amount_paid >= 0",
            name="ck_invoice_amounts",
        ),
        # The arithmetic invariant lives in the database, not only in
        # Python (ADR-0007).
        CheckConstraint("total = subtotal - discount_amount + tax_amount", name="ck_invoice_total"),
        CheckConstraint("due_date >= issue_date", name="ck_invoice_dates"),
        Index("ix_invoices_org_client", "organization_id", "client_id"),
        Index("ix_invoices_org_project", "organization_id", "project_id"),
        Index("ix_invoices_org_created_by", "organization_id", "created_by"),
        Index("ix_invoices_org_status", "organization_id", "status"),
        Index("ix_invoices_org_due_date", "organization_id", "due_date"),
    )


class InvoiceItem(OrgScoped, Base):
    """No timestamps (DATABASE.md §3 lists none) — a line item's own
    history is the invoice's, not its own."""

    __tablename__ = "invoice_items"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    invoice_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    description: Mapped[str] = mapped_column(sa.Text, nullable=False)
    quantity: Mapped[Decimal] = mapped_column(sa.Numeric(12, 3), nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(_MONEY, nullable=False)
    line_total: Mapped[Decimal] = mapped_column(_MONEY, nullable=False)
    position: Mapped[int] = mapped_column(sa.Integer, nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "invoice_id"],
            ["invoices.organization_id", "invoices.id"],
            name="fk_invoice_items_org_invoice_invoices",
            # A line item without its invoice is meaningless; invoices are
            # cancelled/archived, never hard-deleted while items exist, but
            # RESTRICT rather than CASCADE keeps deletion (if ever added)
            # an explicit, deliberate act.
            ondelete="RESTRICT",
        ),
        CheckConstraint("line_total = round(quantity * unit_price, 2)", name="ck_line_total"),
        Index("ix_invoice_items_org_invoice", "organization_id", "invoice_id"),
    )


class Payment(OrgScoped, Base):
    """Append-only (ADR-0007): no update/delete route, no `updated_at`."""

    __tablename__ = "payments"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    invoice_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    amount: Mapped[Decimal] = mapped_column(_MONEY, nullable=False)
    currency: Mapped[str] = mapped_column(sa.Text, nullable=False, server_default="USD")
    paid_on: Mapped[date] = mapped_column(sa.Date, nullable=False)
    method: Mapped[str] = mapped_column(sa.Text, nullable=False)
    reference: Mapped[str | None] = mapped_column(sa.Text, default=None)
    # Person reference -> memberships (DATABASE.md §5.1 names this column
    # explicitly).
    recorded_by: Mapped[uuid.UUID] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(_TZ, server_default=text("now()"))

    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "invoice_id"],
            ["invoices.organization_id", "invoices.id"],
            name="fk_payments_org_invoice_invoices",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["organization_id", "recorded_by"],
            ["memberships.organization_id", "memberships.user_id"],
            name="fk_payments_org_recorded_by_memberships",
            ondelete="RESTRICT",
        ),
        CheckConstraint("amount > 0", name="ck_payment_positive"),
        Index("ix_payments_org_invoice", "organization_id", "invoice_id"),
        Index("ix_payments_org_recorded_by", "organization_id", "recorded_by"),
    )


class InvoiceCounter(OrgScoped, Base):
    """DATABASE.md §3: PK is `(organization_id, year)` itself — no
    surrogate id. `next_invoice_number` (invoice_counter_service.py) takes
    `SELECT ... FOR UPDATE` on this row before incrementing `last_seq`
    (ADR-0007), so two concurrent invoices in the same org/year can never
    compute the same number."""

    __tablename__ = "invoice_counters"

    year: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    last_seq: Mapped[int] = mapped_column(sa.Integer, nullable=False, server_default="0")

    __table_args__ = (PrimaryKeyConstraint("organization_id", "year", name="pk_invoice_counters"),)

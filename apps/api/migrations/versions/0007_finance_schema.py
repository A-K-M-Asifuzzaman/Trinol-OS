"""finance module schema: invoice_counters, invoices, invoice_items,
payments, income, expenses (Phase 5)

Revision ID: 0007_finance_schema
Revises: 0006_meetings_schema
Create Date: 2026-09-10

Hand-written, same reason as every prior schema migration (DATABASE.md
§5.1 composite FKs, native enums) but checked against
modules/finance/models.py so `alembic check` agrees.

Creation order: `invoice_counters` first (no dependency on anything new),
then `invoices` (referenced by `invoice_items`/`payments`/`income.invoice_id`),
then `invoice_items`/`payments`, then `income`/`expenses` last since
`income.invoice_id` needs `invoices` to already exist.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0007_finance_schema"
down_revision: str | None = "0006_meetings_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "CREATE TYPE invoice_status AS ENUM "
        "('DRAFT', 'SENT', 'PARTIALLY_PAID', 'PAID', 'CANCELLED')"
    )
    op.execute(
        "CREATE TYPE expense_category AS ENUM "
        "('HOSTING', 'DOMAINS', 'SOFTWARE', 'MARKETING', 'SALARY', "
        "'CONTRACTOR', 'OFFICE', 'TRAVEL', 'EQUIPMENT', 'OTHER')"
    )

    op.execute(
        """
        CREATE TABLE invoice_counters (
            organization_id uuid NOT NULL REFERENCES organizations (id) ON DELETE RESTRICT,
            year integer NOT NULL,
            last_seq integer NOT NULL DEFAULT 0,
            CONSTRAINT pk_invoice_counters PRIMARY KEY (organization_id, year)
        )
        """
    )

    op.execute(
        """
        CREATE TABLE invoices (
            id uuid PRIMARY KEY,
            organization_id uuid NOT NULL REFERENCES organizations (id) ON DELETE RESTRICT,
            invoice_number text NOT NULL,
            client_id uuid NOT NULL,
            project_id uuid,
            issue_date date NOT NULL,
            due_date date NOT NULL,
            currency text NOT NULL DEFAULT 'USD',
            subtotal numeric(14, 2) NOT NULL,
            discount_amount numeric(14, 2) NOT NULL DEFAULT 0,
            tax_amount numeric(14, 2) NOT NULL DEFAULT 0,
            total numeric(14, 2) NOT NULL,
            amount_paid numeric(14, 2) NOT NULL DEFAULT 0,
            status invoice_status NOT NULL DEFAULT 'DRAFT',
            notes text,
            terms text,
            sent_at timestamptz,
            created_by uuid NOT NULL,
            archived_at timestamptz,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            -- The hard guarantee against duplicate numbers (ADR-0007).
            CONSTRAINT uq_invoice_org_number UNIQUE (organization_id, invoice_number),
            -- Required by composite FKs from invoice_items, payments,
            -- income.invoice_id (DATABASE.md §5.1). Redundant for
            -- uniqueness alone; do not remove as dead weight.
            CONSTRAINT uq_invoices_org_id UNIQUE (organization_id, id),
            CONSTRAINT fk_invoices_org_client_clients FOREIGN KEY (organization_id, client_id)
                REFERENCES clients (organization_id, id) ON DELETE RESTRICT,
            CONSTRAINT fk_invoices_org_project_projects FOREIGN KEY (organization_id, project_id)
                REFERENCES projects (organization_id, id) ON DELETE RESTRICT,
            CONSTRAINT fk_invoices_org_created_by_memberships
                FOREIGN KEY (organization_id, created_by)
                REFERENCES memberships (organization_id, user_id) ON DELETE RESTRICT,
            CONSTRAINT ck_invoice_amounts CHECK (
                subtotal >= 0 AND discount_amount >= 0 AND tax_amount >= 0
                AND total >= 0 AND amount_paid >= 0
            ),
            CONSTRAINT ck_invoice_total CHECK (total = subtotal - discount_amount + tax_amount),
            CONSTRAINT ck_invoice_dates CHECK (due_date >= issue_date)
        )
        """
    )
    op.execute("CREATE INDEX ix_invoices_org_client ON invoices (organization_id, client_id)")
    op.execute("CREATE INDEX ix_invoices_org_project ON invoices (organization_id, project_id)")
    op.execute("CREATE INDEX ix_invoices_org_created_by ON invoices (organization_id, created_by)")
    op.execute("CREATE INDEX ix_invoices_org_status ON invoices (organization_id, status)")
    op.execute("CREATE INDEX ix_invoices_org_due_date ON invoices (organization_id, due_date)")
    op.execute(
        "CREATE TRIGGER trg_invoices_updated_at BEFORE UPDATE ON invoices "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
    )

    op.execute(
        """
        CREATE TABLE invoice_items (
            id uuid PRIMARY KEY,
            organization_id uuid NOT NULL REFERENCES organizations (id) ON DELETE RESTRICT,
            invoice_id uuid NOT NULL,
            description text NOT NULL,
            quantity numeric(12, 3) NOT NULL,
            unit_price numeric(14, 2) NOT NULL,
            line_total numeric(14, 2) NOT NULL,
            "position" integer NOT NULL,
            CONSTRAINT fk_invoice_items_org_invoice_invoices
                FOREIGN KEY (organization_id, invoice_id)
                REFERENCES invoices (organization_id, id) ON DELETE RESTRICT,
            CONSTRAINT ck_line_total CHECK (line_total = round(quantity * unit_price, 2))
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_invoice_items_org_invoice ON invoice_items (organization_id, invoice_id)"
    )

    op.execute(
        """
        CREATE TABLE payments (
            id uuid PRIMARY KEY,
            organization_id uuid NOT NULL REFERENCES organizations (id) ON DELETE RESTRICT,
            invoice_id uuid NOT NULL,
            amount numeric(14, 2) NOT NULL,
            currency text NOT NULL DEFAULT 'USD',
            paid_on date NOT NULL,
            method text NOT NULL,
            reference text,
            recorded_by uuid NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT fk_payments_org_invoice_invoices FOREIGN KEY (organization_id, invoice_id)
                REFERENCES invoices (organization_id, id) ON DELETE RESTRICT,
            CONSTRAINT fk_payments_org_recorded_by_memberships
                FOREIGN KEY (organization_id, recorded_by)
                REFERENCES memberships (organization_id, user_id) ON DELETE RESTRICT,
            CONSTRAINT ck_payment_positive CHECK (amount > 0)
        )
        """
    )
    op.execute("CREATE INDEX ix_payments_org_invoice ON payments (organization_id, invoice_id)")
    op.execute(
        "CREATE INDEX ix_payments_org_recorded_by ON payments (organization_id, recorded_by)"
    )

    op.execute(
        """
        CREATE TABLE income (
            id uuid PRIMARY KEY,
            organization_id uuid NOT NULL REFERENCES organizations (id) ON DELETE RESTRICT,
            amount numeric(14, 2) NOT NULL,
            currency text NOT NULL DEFAULT 'USD',
            source text NOT NULL,
            client_id uuid,
            project_id uuid,
            invoice_id uuid,
            received_on date NOT NULL,
            payment_method text NOT NULL,
            reference text,
            notes text,
            created_by uuid NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT fk_income_org_client_clients FOREIGN KEY (organization_id, client_id)
                REFERENCES clients (organization_id, id) ON DELETE RESTRICT,
            CONSTRAINT fk_income_org_project_projects FOREIGN KEY (organization_id, project_id)
                REFERENCES projects (organization_id, id) ON DELETE RESTRICT,
            CONSTRAINT fk_income_org_invoice_invoices FOREIGN KEY (organization_id, invoice_id)
                REFERENCES invoices (organization_id, id) ON DELETE RESTRICT,
            CONSTRAINT fk_income_org_created_by_memberships
                FOREIGN KEY (organization_id, created_by)
                REFERENCES memberships (organization_id, user_id) ON DELETE RESTRICT,
            CONSTRAINT ck_income_amount_positive CHECK (amount > 0)
        )
        """
    )
    op.execute("CREATE INDEX ix_income_org_received_on ON income (organization_id, received_on)")
    op.execute("CREATE INDEX ix_income_org_client ON income (organization_id, client_id)")
    op.execute("CREATE INDEX ix_income_org_project ON income (organization_id, project_id)")
    op.execute("CREATE INDEX ix_income_org_invoice ON income (organization_id, invoice_id)")
    op.execute("CREATE INDEX ix_income_org_created_by ON income (organization_id, created_by)")
    op.execute(
        "CREATE TRIGGER trg_income_updated_at BEFORE UPDATE ON income "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
    )

    op.execute(
        """
        CREATE TABLE expenses (
            id uuid PRIMARY KEY,
            organization_id uuid NOT NULL REFERENCES organizations (id) ON DELETE RESTRICT,
            amount numeric(14, 2) NOT NULL,
            currency text NOT NULL DEFAULT 'USD',
            category expense_category NOT NULL,
            description text NOT NULL,
            vendor text,
            spent_on date NOT NULL,
            payment_method text NOT NULL,
            receipt_file_id uuid,
            notes text,
            created_by uuid NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT fk_expenses_org_receipt_file_objects
                FOREIGN KEY (organization_id, receipt_file_id)
                REFERENCES file_objects (organization_id, id) ON DELETE RESTRICT,
            CONSTRAINT fk_expenses_org_created_by_memberships
                FOREIGN KEY (organization_id, created_by)
                REFERENCES memberships (organization_id, user_id) ON DELETE RESTRICT,
            CONSTRAINT ck_expense_amount_positive CHECK (amount > 0)
        )
        """
    )
    op.execute("CREATE INDEX ix_expenses_org_spent_on ON expenses (organization_id, spent_on)")
    op.execute("CREATE INDEX ix_expenses_org_category ON expenses (organization_id, category)")
    op.execute(
        "CREATE INDEX ix_expenses_org_receipt ON expenses (organization_id, receipt_file_id)"
    )
    op.execute("CREATE INDEX ix_expenses_org_created_by ON expenses (organization_id, created_by)")
    op.execute(
        "CREATE TRIGGER trg_expenses_updated_at BEFORE UPDATE ON expenses "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
    )


def downgrade() -> None:
    op.execute("DROP TABLE expenses")
    op.execute("DROP TABLE income")
    op.execute("DROP TABLE payments")
    op.execute("DROP TABLE invoice_items")
    op.execute("DROP TABLE invoices")
    op.execute("DROP TABLE invoice_counters")
    op.execute("DROP TYPE expense_category")
    op.execute("DROP TYPE invoice_status")

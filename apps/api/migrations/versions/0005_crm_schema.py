"""crm module schema: clients, leads, lead_stage_events,
contact_submissions, and projects.client_id (Phase 3)

Revision ID: 0005_crm_schema
Revises: 0004_file_objects_attachments
Create Date: 2026-09-09

Hand-written, same reason as 0001/0003/0004 (DATABASE.md §5.1 composite
FKs, native enums) but checked against modules/crm/models.py and the
modules/work/models.py Project.client_id addition so `alembic check`
agrees.

`clients` must be created before `leads` (leads.converted_client_id's
composite FK) and before the `projects.client_id` column is added
(projects.client_id's composite FK) — order matters in this file.

`trinol_app` needs no explicit grant on these new tables: 0001's
`ALTER DEFAULT PRIVILEGES` already covers anything `trinol_migrator`
creates afterward.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0005_crm_schema"
down_revision: str | None = "0004_file_objects_attachments"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE TYPE client_status AS ENUM ('ACTIVE', 'INACTIVE')")
    op.execute(
        "CREATE TYPE lead_source AS ENUM "
        "('WEBSITE', 'FACEBOOK', 'LINKEDIN', 'REFERRAL', 'EMAIL', 'PHONE', 'OTHER')"
    )
    op.execute(
        "CREATE TYPE lead_stage AS ENUM "
        "('NEW', 'CONTACTED', 'MEETING', 'PROPOSAL', 'NEGOTIATION', 'WON', 'LOST')"
    )

    op.execute(
        """
        CREATE TABLE clients (
            id uuid PRIMARY KEY,
            organization_id uuid NOT NULL REFERENCES organizations (id) ON DELETE RESTRICT,
            name text NOT NULL,
            company text,
            email text,
            phone text,
            website text,
            address text,
            notes text,
            status client_status NOT NULL DEFAULT 'ACTIVE',
            owner_id uuid,
            archived_at timestamptz,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            -- Required by composite FKs from projects.client_id,
            -- leads.converted_client_id, and future-phase meetings/income/
            -- invoices/document_references.client_id (DATABASE.md §5.1).
            -- Redundant for uniqueness alone; do not remove as dead weight.
            CONSTRAINT uq_clients_org_id UNIQUE (organization_id, id),
            CONSTRAINT fk_clients_org_owner_memberships FOREIGN KEY (organization_id, owner_id)
                REFERENCES memberships (organization_id, user_id) ON DELETE RESTRICT
        )
        """
    )
    op.execute("CREATE INDEX ix_clients_org_owner ON clients (organization_id, owner_id)")
    op.execute(
        "CREATE TRIGGER trg_clients_updated_at BEFORE UPDATE ON clients "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
    )

    op.execute(
        """
        CREATE TABLE leads (
            id uuid PRIMARY KEY,
            organization_id uuid NOT NULL REFERENCES organizations (id) ON DELETE RESTRICT,
            name text NOT NULL,
            company text,
            email text,
            phone text,
            source lead_source NOT NULL,
            service text,
            estimated_value numeric(14, 2),
            currency text NOT NULL DEFAULT 'USD',
            stage lead_stage NOT NULL DEFAULT 'NEW',
            assigned_to uuid,
            next_follow_up date,
            notes text,
            converted_client_id uuid,
            converted_at timestamptz,
            lost_reason text,
            board_position numeric NOT NULL DEFAULT 0,
            archived_at timestamptz,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            -- Required by lead_stage_events.lead_id and
            -- contact_submissions.lead_id's composite FKs (DATABASE.md §5.1).
            CONSTRAINT uq_leads_org_id UNIQUE (organization_id, id),
            CONSTRAINT fk_leads_org_assigned_to_memberships
                FOREIGN KEY (organization_id, assigned_to)
                REFERENCES memberships (organization_id, user_id) ON DELETE RESTRICT,
            CONSTRAINT fk_leads_org_converted_client_clients
                FOREIGN KEY (organization_id, converted_client_id)
                REFERENCES clients (organization_id, id) ON DELETE RESTRICT,
            CONSTRAINT ck_lead_contact CHECK (email IS NOT NULL OR phone IS NOT NULL)
        )
        """
    )
    op.execute("CREATE INDEX ix_leads_org_stage ON leads (organization_id, stage)")
    op.execute("CREATE INDEX ix_leads_org_followup ON leads (organization_id, next_follow_up)")
    # fk_leads_org_assigned_to_memberships and
    # fk_leads_org_converted_client_clients aren't covered by either index
    # above (DATABASE.md §1).
    op.execute("CREATE INDEX ix_leads_org_assigned_to ON leads (organization_id, assigned_to)")
    op.execute(
        "CREATE INDEX ix_leads_org_converted_client ON leads (organization_id, converted_client_id)"
    )
    op.execute(
        "CREATE TRIGGER trg_leads_updated_at BEFORE UPDATE ON leads "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
    )

    op.execute(
        """
        CREATE TABLE lead_stage_events (
            id uuid PRIMARY KEY,
            organization_id uuid NOT NULL REFERENCES organizations (id) ON DELETE RESTRICT,
            lead_id uuid NOT NULL,
            from_stage lead_stage,
            to_stage lead_stage NOT NULL,
            actor_id uuid REFERENCES users (id) ON DELETE SET NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT fk_lead_stage_events_org_lead_leads FOREIGN KEY (organization_id, lead_id)
                REFERENCES leads (organization_id, id) ON DELETE CASCADE
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_lead_stage_events_org_lead ON lead_stage_events (organization_id, lead_id)"
    )

    op.execute(
        """
        CREATE TABLE contact_submissions (
            id uuid PRIMARY KEY,
            organization_id uuid NOT NULL REFERENCES organizations (id) ON DELETE RESTRICT,
            name text NOT NULL,
            email text NOT NULL,
            phone text,
            company text,
            service text,
            budget text,
            message text NOT NULL,
            ip inet,
            user_agent text,
            reference_number text NOT NULL,
            lead_id uuid,
            spam_score numeric(5, 2),
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_contact_submissions_org_reference
                UNIQUE (organization_id, reference_number),
            CONSTRAINT fk_contact_submissions_org_lead_leads FOREIGN KEY (organization_id, lead_id)
                REFERENCES leads (organization_id, id) ON DELETE RESTRICT
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_contact_submissions_org_lead "
        "ON contact_submissions (organization_id, lead_id)"
    )

    op.execute("ALTER TABLE projects ADD COLUMN client_id uuid")
    op.execute(
        """
        ALTER TABLE projects
        ADD CONSTRAINT fk_projects_org_client_clients
        FOREIGN KEY (organization_id, client_id) REFERENCES clients (organization_id, id)
        ON DELETE RESTRICT
        """
    )
    op.execute("CREATE INDEX ix_projects_org_client ON projects (organization_id, client_id)")


def downgrade() -> None:
    op.execute("DROP INDEX ix_projects_org_client")
    op.execute("ALTER TABLE projects DROP CONSTRAINT fk_projects_org_client_clients")
    op.execute("ALTER TABLE projects DROP COLUMN client_id")

    op.execute("DROP TABLE contact_submissions")
    op.execute("DROP TABLE lead_stage_events")
    op.execute("DROP TABLE leads")
    op.execute("DROP TABLE clients")

    op.execute("DROP TYPE lead_stage")
    op.execute("DROP TYPE lead_source")
    op.execute("DROP TYPE client_status")

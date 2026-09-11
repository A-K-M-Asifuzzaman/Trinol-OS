"""document_references (Phase 6)

Revision ID: 0008_document_references
Revises: 0007_finance_schema
Create Date: 2026-09-11

Hand-written, same reason as every prior schema migration (DATABASE.md
§5.1 composite FKs, native enums) but checked against
platform/models.py so `alembic check` agrees.

A plain external-link table (ADR-0012: "V1 stores external links" for
Google Drive, extended to GitHub/other systems via `kind` — Phase 6 plan),
not a `file_objects` wrapper. No unique constraint of its own — nothing
composite-FKs to a `document_references` row.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0008_document_references"
down_revision: str | None = "0007_finance_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE TYPE document_kind AS ENUM ('GOOGLE_DRIVE', 'GITHUB', 'OTHER')")

    op.execute(
        """
        CREATE TABLE document_references (
            id uuid PRIMARY KEY,
            organization_id uuid NOT NULL REFERENCES organizations (id) ON DELETE RESTRICT,
            title text NOT NULL,
            url text NOT NULL,
            kind document_kind NOT NULL,
            project_id uuid,
            client_id uuid,
            meeting_id uuid,
            added_by uuid NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT fk_document_references_org_project_projects
                FOREIGN KEY (organization_id, project_id)
                REFERENCES projects (organization_id, id) ON DELETE RESTRICT,
            CONSTRAINT fk_document_references_org_client_clients
                FOREIGN KEY (organization_id, client_id)
                REFERENCES clients (organization_id, id) ON DELETE RESTRICT,
            CONSTRAINT fk_document_references_org_meeting_meetings
                FOREIGN KEY (organization_id, meeting_id)
                REFERENCES meetings (organization_id, id) ON DELETE RESTRICT,
            CONSTRAINT fk_document_references_org_added_by_memberships
                FOREIGN KEY (organization_id, added_by)
                REFERENCES memberships (organization_id, user_id) ON DELETE RESTRICT
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_document_references_org_project "
        "ON document_references (organization_id, project_id)"
    )
    op.execute(
        "CREATE INDEX ix_document_references_org_client "
        "ON document_references (organization_id, client_id)"
    )
    op.execute(
        "CREATE INDEX ix_document_references_org_meeting "
        "ON document_references (organization_id, meeting_id)"
    )
    op.execute(
        "CREATE INDEX ix_document_references_org_added_by "
        "ON document_references (organization_id, added_by)"
    )
    op.execute(
        "CREATE TRIGGER trg_document_references_updated_at BEFORE UPDATE ON document_references "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
    )


def downgrade() -> None:
    op.execute("DROP TABLE document_references")
    op.execute("DROP TYPE document_kind")

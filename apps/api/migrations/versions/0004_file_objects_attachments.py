"""file_objects, task_attachments, and organizations.logo_file_id (Phase 2
Stage 6)

Revision ID: 0004_file_objects_attachments
Revises: 0003_work_schema
Create Date: 2026-09-09

Hand-written, same reason as 0001/0003 (composite FKs, checked against the
ORM metadata so `alembic check` agrees).

Restores `organizations.logo_file_id`, deferred since Stage 1/3 for exactly
this reason: the composite FK needs `file_objects` to exist first. Per
DATABASE.md §3 this uses `ON DELETE RESTRICT`, not `SET NULL` — on a
composite FK Postgres nulls every referencing column, and `id` is
`organizations`' own primary key, which can never be null.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0004_file_objects_attachments"
down_revision: str | None = "0003_work_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE file_objects (
            id uuid PRIMARY KEY,
            organization_id uuid NOT NULL REFERENCES organizations (id) ON DELETE RESTRICT,
            storage_key text NOT NULL,
            filename text NOT NULL,
            content_type text NOT NULL,
            size_bytes integer NOT NULL,
            checksum_sha256 text NOT NULL,
            uploaded_by uuid NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_file_objects_storage_key UNIQUE (storage_key),
            -- Required by organizations.logo_file_id's and
            -- task_attachments.file_id's composite FKs (DATABASE.md §5.1).
            CONSTRAINT uq_file_objects_org_id UNIQUE (organization_id, id),
            CONSTRAINT fk_file_objects_org_uploaded_by_memberships
                FOREIGN KEY (organization_id, uploaded_by)
                REFERENCES memberships (organization_id, user_id) ON DELETE RESTRICT
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_file_objects_org_uploaded_by "
        "ON file_objects (organization_id, uploaded_by)"
    )

    op.execute("ALTER TABLE organizations ADD COLUMN logo_file_id uuid")
    op.execute(
        """
        ALTER TABLE organizations
        ADD CONSTRAINT fk_organizations_id_logo_file_id_file_objects
        FOREIGN KEY (id, logo_file_id) REFERENCES file_objects (organization_id, id)
        ON DELETE RESTRICT
        """
    )

    op.execute(
        """
        CREATE TABLE task_attachments (
            id uuid PRIMARY KEY,
            organization_id uuid NOT NULL REFERENCES organizations (id) ON DELETE RESTRICT,
            task_id uuid NOT NULL,
            file_id uuid NOT NULL,
            uploaded_by uuid NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT fk_task_attachments_org_task_tasks
                FOREIGN KEY (organization_id, task_id)
                REFERENCES tasks (organization_id, id) ON DELETE CASCADE,
            CONSTRAINT fk_task_attachments_org_file_file_objects
                FOREIGN KEY (organization_id, file_id)
                REFERENCES file_objects (organization_id, id) ON DELETE RESTRICT,
            CONSTRAINT fk_task_attachments_org_uploaded_by_memberships
                FOREIGN KEY (organization_id, uploaded_by)
                REFERENCES memberships (organization_id, user_id) ON DELETE RESTRICT
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_task_attachments_org_task ON task_attachments (organization_id, task_id)"
    )
    op.execute(
        "CREATE INDEX ix_task_attachments_org_file ON task_attachments (organization_id, file_id)"
    )
    op.execute(
        "CREATE INDEX ix_task_attachments_org_uploaded_by "
        "ON task_attachments (organization_id, uploaded_by)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE task_attachments")
    op.execute(
        "ALTER TABLE organizations DROP CONSTRAINT fk_organizations_id_logo_file_id_file_objects"
    )
    op.execute("ALTER TABLE organizations DROP COLUMN logo_file_id")
    op.execute("DROP TABLE file_objects")

"""ai: meeting_summaries (Phase 8 Stage 1)

Revision ID: 0009_ai_meeting_summaries
Revises: 0008_document_references
Create Date: 2026-09-12

Hand-written, same reason as every prior schema migration (DATABASE.md
§5.1 composite FKs) but checked against modules/ai/models.py so
`alembic check` agrees.

1:1 with meetings.id, regenerated in place (no version history) — the
first table of the new `ai` module (ADR-0014, ARCHITECTURE.md §3).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0009_ai_meeting_summaries"
down_revision: str | None = "0008_document_references"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE meeting_summaries (
            id uuid PRIMARY KEY,
            organization_id uuid NOT NULL REFERENCES organizations (id) ON DELETE RESTRICT,
            meeting_id uuid NOT NULL,
            content text NOT NULL,
            model text NOT NULL,
            generated_by uuid NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_meeting_summaries_org_meeting UNIQUE (organization_id, meeting_id),
            CONSTRAINT fk_meeting_summaries_org_meeting_meetings
                FOREIGN KEY (organization_id, meeting_id)
                REFERENCES meetings (organization_id, id) ON DELETE CASCADE,
            CONSTRAINT fk_meeting_summaries_org_generated_by_memberships
                FOREIGN KEY (organization_id, generated_by)
                REFERENCES memberships (organization_id, user_id) ON DELETE RESTRICT
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_meeting_summaries_org_generated_by "
        "ON meeting_summaries (organization_id, generated_by)"
    )
    op.execute(
        "CREATE TRIGGER trg_meeting_summaries_updated_at BEFORE UPDATE ON meeting_summaries "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
    )


def downgrade() -> None:
    op.execute("DROP TABLE meeting_summaries")

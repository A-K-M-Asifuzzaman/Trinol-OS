"""ai: lead_scores (Phase 8 Stage 5)

Revision ID: 0012_ai_lead_scores
Revises: 0011_ai_knowledge_chunks
Create Date: 2026-09-12

Hand-written, same reason as every prior schema migration (DATABASE.md
§5.1 composite FKs) but checked against modules/ai/models.py so
`alembic check` agrees.

1:1 with leads.id, regenerated in place (no version history) — same
shape as meeting_summaries (Stage 1).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0012_ai_lead_scores"
down_revision: str | None = "0011_ai_knowledge_chunks"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE lead_scores (
            id uuid PRIMARY KEY,
            organization_id uuid NOT NULL REFERENCES organizations (id) ON DELETE RESTRICT,
            lead_id uuid NOT NULL,
            score integer NOT NULL,
            rationale text NOT NULL,
            computed_at timestamptz NOT NULL DEFAULT now(),
            computed_by uuid NOT NULL,
            CONSTRAINT uq_lead_scores_org_lead UNIQUE (organization_id, lead_id),
            CONSTRAINT fk_lead_scores_org_lead_leads
                FOREIGN KEY (organization_id, lead_id)
                REFERENCES leads (organization_id, id) ON DELETE RESTRICT,
            CONSTRAINT fk_lead_scores_org_computed_by_memberships
                FOREIGN KEY (organization_id, computed_by)
                REFERENCES memberships (organization_id, user_id) ON DELETE RESTRICT
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_lead_scores_org_computed_by ON lead_scores (organization_id, computed_by)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE lead_scores")

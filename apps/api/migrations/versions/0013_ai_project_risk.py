"""ai: project_risk_assessments (Phase 8 Stage 6)

Revision ID: 0013_ai_project_risk
Revises: 0012_ai_lead_scores
Create Date: 2026-09-12

Hand-written, same reason as every prior schema migration (DATABASE.md
§5.1 composite FKs, native enums) but checked against
modules/ai/models.py so `alembic check` agrees.

1:1 with projects.id, regenerated in place (no version history) — same
shape as meeting_summaries/lead_scores (Stages 1/5). `level` is always
recomputed live at read time and never trusted from this table alone;
only `narrative`/`signals_snapshot` are meaningfully cached here.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0013_ai_project_risk"
down_revision: str | None = "0012_ai_lead_scores"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE TYPE project_risk_level AS ENUM ('LOW', 'MEDIUM', 'HIGH')")
    op.execute(
        """
        CREATE TABLE project_risk_assessments (
            id uuid PRIMARY KEY,
            organization_id uuid NOT NULL REFERENCES organizations (id) ON DELETE RESTRICT,
            project_id uuid NOT NULL,
            level project_risk_level NOT NULL,
            narrative text NOT NULL,
            signals_snapshot jsonb NOT NULL,
            computed_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_project_risk_assessments_org_project
                UNIQUE (organization_id, project_id),
            CONSTRAINT fk_project_risk_assessments_org_project_projects
                FOREIGN KEY (organization_id, project_id)
                REFERENCES projects (organization_id, id) ON DELETE RESTRICT
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE project_risk_assessments")
    op.execute("DROP TYPE project_risk_level")

"""ai: record who generated project-risk narratives

Revision ID: 0014_project_risk_computed_by
Revises: 0013_ai_project_risk
Create Date: 2026-09-12

Existing rows stay nullable because their original actor cannot be recovered
truthfully. The service treats those cache rows as stale and regenerates them
with a real membership-backed actor on the next single-project assessment.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0014_project_risk_computed_by"
down_revision: str | None = "0013_ai_project_risk"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE project_risk_assessments ADD COLUMN computed_by uuid")
    op.execute(
        """
        ALTER TABLE project_risk_assessments
        ADD CONSTRAINT fk_project_risk_org_computed_by_memberships
        FOREIGN KEY (organization_id, computed_by)
        REFERENCES memberships (organization_id, user_id) ON DELETE RESTRICT
        """
    )
    op.execute(
        "CREATE INDEX ix_project_risk_org_computed_by "
        "ON project_risk_assessments (organization_id, computed_by)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX ix_project_risk_org_computed_by")
    op.execute(
        "ALTER TABLE project_risk_assessments "
        "DROP CONSTRAINT fk_project_risk_org_computed_by_memberships"
    )
    op.execute("ALTER TABLE project_risk_assessments DROP COLUMN computed_by")

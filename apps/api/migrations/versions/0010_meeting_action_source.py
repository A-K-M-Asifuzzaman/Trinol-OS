"""meetings: meeting_actions.source (Phase 8 Stage 2)

Revision ID: 0010_meeting_action_source
Revises: 0009_ai_meeting_summaries
Create Date: 2026-09-12

Hand-written, same reason as every prior schema migration (DATABASE.md
§5.1 composite FKs, native enums) but checked against
modules/meetings/models.py so `alembic check` agrees.

A meetings-owned schema change, not an ai-owned write (ARCHITECTURE.md
§3, Phase 8 plan) — distinguishes a human-authored action item from one
`ai.services.action_extraction_service.extract_actions` suggested.
Defaults every existing row to HUMAN, which is what it always meant.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0010_meeting_action_source"
down_revision: str | None = "0009_ai_meeting_summaries"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE TYPE meeting_action_source AS ENUM ('HUMAN', 'AI')")
    op.execute(
        "ALTER TABLE meeting_actions ADD COLUMN source meeting_action_source "
        "NOT NULL DEFAULT 'HUMAN'"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE meeting_actions DROP COLUMN source")
    op.execute("DROP TYPE meeting_action_source")

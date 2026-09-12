"""ai: knowledge_chunks + pgvector (Phase 8 Stage 3)

Revision ID: 0011_ai_knowledge_chunks
Revises: 0010_meeting_action_source
Create Date: 2026-09-12

Hand-written, same reason as every prior schema migration (DATABASE.md
§5.1 composite FKs, native enums) but checked against
modules/ai/models.py so `alembic check` agrees.

ADR-0014: pgvector is not a "trusted" extension, so only a superuser can
install it -- infrastructure/postgres/init.sql does that at provisioning
time (dev/CI both run as a superuser then), making the statement below
always a no-op "already exists" by the time this migration runs.

`knowledge_chunks` is polymorphic (`source_type`/`source_id`, not an FK)
-- same reasoning `activity_events.entity_id` already uses. No `FINANCE`
value exists in `knowledge_source_type` at all (ADR-0014 SS0(b)):
Income/Expense/Invoice/Payment are never embedded, structurally.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0011_ai_knowledge_chunks"
down_revision: str | None = "0010_meeting_action_source"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE TYPE knowledge_source_type AS ENUM ('MEETING', 'LEAD', 'PROJECT', 'TASK')")
    op.execute(
        """
        CREATE TABLE knowledge_chunks (
            id uuid PRIMARY KEY,
            organization_id uuid NOT NULL REFERENCES organizations (id) ON DELETE RESTRICT,
            source_type knowledge_source_type NOT NULL,
            source_id uuid NOT NULL,
            source_updated_at timestamptz NOT NULL,
            chunk_index integer NOT NULL DEFAULT 0,
            content text NOT NULL,
            embedding vector(1536) NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_knowledge_chunks_org_source
                UNIQUE (organization_id, source_type, source_id, chunk_index)
        )
        """
    )
    # ANN index for cosine-distance search (retrieval_service, Stage 4) --
    # declared in modules/ai/models.py's own __table_args__ (postgresql_
    # using="hnsw"/postgresql_ops), so `alembic check` can verify it same
    # as every other index; raw SQL here just matches what that
    # declaration produces.
    op.execute(
        "CREATE INDEX ix_knowledge_chunks_embedding_hnsw ON knowledge_chunks "
        "USING hnsw (embedding vector_cosine_ops)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE knowledge_chunks")
    op.execute("DROP TYPE knowledge_source_type")

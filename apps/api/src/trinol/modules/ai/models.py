from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, FetchedValue, ForeignKeyConstraint, Index, UniqueConstraint, text
from sqlalchemy import Enum as PgEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from trinol.core.db.base import Base
from trinol.core.db.org_scoped import OrgScoped
from trinol.core.ids import uuid7

_TZ = sa.DateTime(timezone=True)

# text-embedding-3-small's native dimension (OPENAI_EMBEDDING_MODEL's
# default, core/config.py) — the pgvector column is fixed-width, so
# switching embedding models to one with a different dimension would need
# a new migration, not just a config change.
EMBEDDING_DIMENSIONS = 1536


class MeetingSummary(OrgScoped, Base):
    """Phase 8 Stage 1 (ADR-0014). 1:1 with `meetings.id`, regenerated in
    place on every `summarize_meeting()` call — no version history, same
    "current state only" shape `ProjectRiskAssessment`/`LeadScore` (later
    stages) will also use. Visibility is entirely the parent meeting's own
    (`meeting_service.ensure_meeting_visible`) — this table carries no
    separate permission or ownership rule of its own."""

    __tablename__ = "meeting_summaries"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    meeting_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    content: Mapped[str] = mapped_column(sa.Text, nullable=False)
    # Which OPENAI_CHAT_MODEL produced this — debugging/audit only, not
    # used for anything at read time.
    model: Mapped[str] = mapped_column(sa.Text, nullable=False)
    # Person reference -> memberships, not users (DATABASE.md §5.1).
    generated_by: Mapped[uuid.UUID] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(_TZ, server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(
        _TZ, server_default=text("now()"), server_onupdate=FetchedValue()
    )

    __table_args__ = (
        UniqueConstraint("organization_id", "meeting_id", name="uq_meeting_summaries_org_meeting"),
        ForeignKeyConstraint(
            ["organization_id", "meeting_id"],
            ["meetings.organization_id", "meetings.id"],
            name="fk_meeting_summaries_org_meeting_meetings",
            # ADR-0011: meetings are hard-deleted; a summary without its
            # meeting is meaningless.
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["organization_id", "generated_by"],
            ["memberships.organization_id", "memberships.user_id"],
            name="fk_meeting_summaries_org_generated_by_memberships",
            ondelete="RESTRICT",
        ),
        # uq_meeting_summaries_org_meeting above already covers the
        # meeting_id FK (DATABASE.md §1: "left prefix of a composite one").
        Index("ix_meeting_summaries_org_generated_by", "organization_id", "generated_by"),
    )


class KnowledgeSourceType(StrEnum):
    """Phase 8 Stage 3 (ADR-0014 §0(b)): deliberately no `FINANCE` member.
    `Income`/`Expense`/`Invoice`/`Payment` are never chunked or embedded —
    the company assistant's only access to financial figures is a direct,
    already-`FINANCE_READ`-gated service call (Stage 4), never a vector
    search. This is structural, not a filter: there is no code path that
    could ever produce a finance `KnowledgeChunk` row, because there is no
    such enum member to construct one with."""

    MEETING = "MEETING"
    LEAD = "LEAD"
    PROJECT = "PROJECT"
    TASK = "TASK"


class KnowledgeChunk(OrgScoped, Base):
    """Phase 8 Stage 3. Polymorphic (`source_type`/`source_id`, not an FK —
    same reasoning `platform.ActivityEvent.entity_id` already uses for a
    row that can point at any one of several tables). One chunk per source
    row today (`chunk_index` always 0 — no real text splitter is needed at
    this data volume; kept so a future real splitter doesn't need a schema
    change). `content` is the literal text that was embedded and is what
    gets injected into an LLM's context at retrieval time — never
    re-derived from the embedding itself.

    Deliberately no cached role/visibility column: retrieval (Stage 4)
    never trusts anything cached here for authorization, always
    re-validating live against the source's own module — see ADR-0014."""

    __tablename__ = "knowledge_chunks"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    source_type: Mapped[KnowledgeSourceType] = mapped_column(
        PgEnum(
            KnowledgeSourceType,
            name="knowledge_source_type",
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
    )
    source_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    # Copy of the source row's own updated_at — drives staleness detection
    # in embedding_service.reindex_stale (no chunk, or this older than the
    # source's current updated_at, means re-embed).
    source_updated_at: Mapped[datetime] = mapped_column(_TZ, nullable=False)
    chunk_index: Mapped[int] = mapped_column(nullable=False, default=0)
    content: Mapped[str] = mapped_column(sa.Text, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIMENSIONS), nullable=False)
    created_at: Mapped[datetime] = mapped_column(_TZ, server_default=text("now()"))

    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "source_type",
            "source_id",
            "chunk_index",
            name="uq_knowledge_chunks_org_source",
        ),
        # ANN index for cosine-distance search (retrieval_service, Stage
        # 4) — declared here (not left as migration-only raw SQL) so
        # `alembic check` can actually verify it, same as every other
        # index in this codebase.
        Index(
            "ix_knowledge_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )


class LeadScore(OrgScoped, Base):
    """Phase 8 Stage 5. 1:1 with `crm.leads.id`, regenerated in place on
    every `score_lead()` call — same "current state only" shape
    `MeetingSummary` already uses. Visibility is entirely the lead's own
    (`LEAD_READ`, org-wide, no ownership-split per RBAC.md) — this table
    carries no separate rule of its own. `score` is LLM-authored directly
    (unlike `ProjectRiskAssessment.level`, later stage) — a lead score is
    advisory, not a number this project's leadership would ever treat as
    an authoritative total the way a financial figure is, so §30's "no
    LLM financial totals" rule doesn't apply here."""

    __tablename__ = "lead_scores"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    lead_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    # 0-100, clamped in lead_scoring_service — never trusts the model's
    # own arithmetic to stay in range.
    score: Mapped[int] = mapped_column(nullable=False)
    rationale: Mapped[str] = mapped_column(sa.Text, nullable=False)
    computed_at: Mapped[datetime] = mapped_column(_TZ, server_default=text("now()"))
    # Person reference -> memberships, not users (DATABASE.md §5.1).
    computed_by: Mapped[uuid.UUID] = mapped_column(nullable=False)

    __table_args__ = (
        UniqueConstraint("organization_id", "lead_id", name="uq_lead_scores_org_lead"),
        ForeignKeyConstraint(
            ["organization_id", "lead_id"],
            ["leads.organization_id", "leads.id"],
            name="fk_lead_scores_org_lead_leads",
            # Leads are soft-deleted (archived_at), never hard-deleted —
            # RESTRICT, same reasoning every other lead-referencing FK
            # elsewhere in this codebase already uses.
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["organization_id", "computed_by"],
            ["memberships.organization_id", "memberships.user_id"],
            name="fk_lead_scores_org_computed_by_memberships",
            ondelete="RESTRICT",
        ),
        # uq_lead_scores_org_lead above already covers the lead_id FK
        # (DATABASE.md §1: "left prefix of a composite one").
        Index("ix_lead_scores_org_computed_by", "organization_id", "computed_by"),
    )


class ProjectRiskLevel(StrEnum):
    """Phase 8 Stage 6. Always computed by a fixed threshold rule over
    `work.services.analytics_service.get_project_analytics()` output plus
    `Project.health`/`deadline` — never by the LLM (generalizes §30's "no
    LLM financial totals" rule to any figure this project's leadership
    would treat as authoritative)."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class ProjectRiskAssessment(OrgScoped, Base):
    """Phase 8 Stage 6. 1:1 with `work.projects.id`, regenerated in place
    — same shape `MeetingSummary`/`LeadScore` already use. `level` is
    recomputed deterministically on every read (never cached — cheap,
    and never trusted stale); only `narrative` (the LLM-authored prose
    explaining `level`) is cached, and only regenerated when
    `signals_snapshot` no longer matches what a fresh computation would
    produce. Visibility is entirely the project's own (`project_service.
    ensure_project_visible`) — this table carries no separate rule."""

    __tablename__ = "project_risk_assessments"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    project_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    # Persisted alongside the narrative it was written from — not the
    # authoritative level (that's always recomputed live), just a record
    # of what the cached narrative is about.
    level: Mapped[ProjectRiskLevel] = mapped_column(
        PgEnum(
            ProjectRiskLevel,
            name="project_risk_level",
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
    )
    narrative: Mapped[str] = mapped_column(sa.Text, nullable=False)
    # The exact deterministic inputs the narrative was written from, so a
    # later read can tell "did anything relevant change" without another
    # LLM call — JSONB, mirrors platform.models.ActivityEvent.
    # event_metadata's own type exactly.
    signals_snapshot: Mapped[dict[str, object]] = mapped_column(
        JSONB().with_variant(JSON(), "sqlite"),
        nullable=False,
    )
    computed_at: Mapped[datetime] = mapped_column(_TZ, server_default=text("now()"))
    # Nullable only for rows created before migration 0014. Services never
    # surface those legacy narratives as fresh; the next single-project
    # assessment regenerates them with a real actor.
    computed_by: Mapped[uuid.UUID | None] = mapped_column(default=None)

    __table_args__ = (
        UniqueConstraint(
            "organization_id", "project_id", name="uq_project_risk_assessments_org_project"
        ),
        ForeignKeyConstraint(
            ["organization_id", "project_id"],
            ["projects.organization_id", "projects.id"],
            name="fk_project_risk_assessments_org_project_projects",
            # Projects are soft-deleted (archived_at), never hard-deleted
            # — RESTRICT, same reasoning every other project-referencing
            # FK elsewhere in this codebase already uses.
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["organization_id", "computed_by"],
            ["memberships.organization_id", "memberships.user_id"],
            name="fk_project_risk_org_computed_by_memberships",
            ondelete="RESTRICT",
        ),
        # uq_project_risk_assessments_org_project above already covers
        # the project_id FK (DATABASE.md §1: "left prefix of a composite
        # one").
        Index("ix_project_risk_org_computed_by", "organization_id", "computed_by"),
    )

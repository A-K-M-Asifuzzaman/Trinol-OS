from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy import JSON, ForeignKey, Index, text
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from trinol.core.db.base import Base
from trinol.core.db.org_scoped import OrgScoped
from trinol.core.ids import uuid7

_TZ = sa.DateTime(timezone=True)


class ActivityEvent(OrgScoped, Base):
    """Append-only: serves both the activity feed and the audit log via
    `is_audit` (ADR-0006). The `trinol_app` role has no UPDATE/DELETE grant on
    this table — enforced by the migration, not by this class."""

    __tablename__ = "activity_events"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    # Exception to the "references reach memberships, not users" rule
    # (DATABASE.md §5.1): history must survive the actor leaving the org.
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    event: Mapped[str] = mapped_column(sa.Text, nullable=False)
    entity_type: Mapped[str] = mapped_column(sa.Text, nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    # Python attribute can't be named `metadata` — it collides with
    # DeclarativeBase.metadata. The DB column is still called `metadata`.
    event_metadata: Mapped[dict[str, object]] = mapped_column(
        "metadata",
        JSONB().with_variant(JSON(), "sqlite"),
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    is_audit: Mapped[bool] = mapped_column(nullable=False, server_default=text("false"))
    ip: Mapped[str | None] = mapped_column(INET, default=None)
    created_at: Mapped[datetime] = mapped_column(_TZ, server_default=text("now()"))

    __table_args__ = (
        Index("ix_activity_org_created", "organization_id", sa.text("created_at DESC")),
        Index("ix_activity_entity", "organization_id", "entity_type", "entity_id"),
    )


class RateLimitBucket(Base):
    """Fixed-window limiter, updated by one atomic `INSERT ... ON CONFLICT DO
    UPDATE` (ADR-0010) — never read-increment-write across statements."""

    __tablename__ = "rate_limit_buckets"

    key: Mapped[str] = mapped_column(sa.Text, primary_key=True)
    window_start: Mapped[datetime] = mapped_column(_TZ, nullable=False)
    count: Mapped[int] = mapped_column(nullable=False, server_default=text("0"))

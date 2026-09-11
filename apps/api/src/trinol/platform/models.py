from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

import sqlalchemy as sa
from sqlalchemy import (
    JSON,
    FetchedValue,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    UniqueConstraint,
    text,
)
from sqlalchemy import Enum as PgEnum
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


class FileObject(OrgScoped, Base):
    """ADR-0008/DATABASE.md §3 (platform). Metadata only — the blob lives in
    whatever `FileStorage` backend is configured. `storage_key` is globally
    unique (it already embeds `organization_id`, per platform/files.py's
    `{org_id}/{uuid7}{ext}` format, so a per-org constraint would be no
    stricter)."""

    __tablename__ = "file_objects"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    storage_key: Mapped[str] = mapped_column(sa.Text, unique=True, nullable=False)
    filename: Mapped[str] = mapped_column(sa.Text, nullable=False)
    content_type: Mapped[str] = mapped_column(sa.Text, nullable=False)
    size_bytes: Mapped[int] = mapped_column(nullable=False)
    checksum_sha256: Mapped[str] = mapped_column(sa.Text, nullable=False)
    uploaded_by: Mapped[uuid.UUID] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(_TZ, server_default=text("now()"))

    __table_args__ = (
        # Required by organizations.logo_file_id's and
        # task_attachments.file_id's composite FKs (DATABASE.md §5.1).
        UniqueConstraint("organization_id", "id", name="uq_file_objects_org_id"),
        ForeignKeyConstraint(
            ["organization_id", "uploaded_by"],
            ["memberships.organization_id", "memberships.user_id"],
            name="fk_file_objects_org_uploaded_by_memberships",
            # Non-nullable authorship column (DATABASE.md §5.2): RESTRICT.
            ondelete="RESTRICT",
        ),
        Index("ix_file_objects_org_uploaded_by", "organization_id", "uploaded_by"),
    )


class DocumentKind(StrEnum):
    """DATABASE.md §3 (platform) leaves `kind`'s values undefined — invented
    this phase (Phase 6 plan decision 1), directly matching ROADMAP.md's own
    three non-"document references" checklist bullets one-to-one: Google
    Drive, GitHub, and "additional useful integrations" (`OTHER`, a
    catch-all). `ponytail: extend if a specific system earns its own icon/
    filter later — nothing forces more values now."""

    GOOGLE_DRIVE = "GOOGLE_DRIVE"
    GITHUB = "GITHUB"
    OTHER = "OTHER"


class DocumentReference(OrgScoped, Base):
    """DATABASE.md §3 (platform) / ADR-0012: "V1 stores external links" for
    Google Drive, extended to GitHub and other systems by the same
    reasoning (Phase 6 plan) — a plain URL-reference table, not a
    `file_objects` wrapper; no upload, no OAuth. `project_id`/`client_id`/
    `meeting_id` are each independently optional and not mutually
    exclusive (Phase 6 plan decision 4) — a parent-less row is a
    legitimate general org-wide link. Not one of ADR-0011's four
    `archived_at` entities, so no `archived_at` here; deletion is a hard
    delete with an audit event (Phase 6 plan decision 5)."""

    __tablename__ = "document_references"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    title: Mapped[str] = mapped_column(sa.Text, nullable=False)
    url: Mapped[str] = mapped_column(sa.Text, nullable=False)
    kind: Mapped[DocumentKind] = mapped_column(
        PgEnum(
            DocumentKind,
            name="document_kind",
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(default=None)
    client_id: Mapped[uuid.UUID | None] = mapped_column(default=None)
    meeting_id: Mapped[uuid.UUID | None] = mapped_column(default=None)
    # Person reference -> memberships, not users (DATABASE.md §5.1). Matches
    # DATABASE.md's own literal column name, not `created_by`.
    added_by: Mapped[uuid.UUID] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(_TZ, server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(
        _TZ, server_default=text("now()"), server_onupdate=FetchedValue()
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "project_id"],
            ["projects.organization_id", "projects.id"],
            name="fk_document_references_org_project_projects",
            # Nullable; projects are soft-deleted only (ADR-0011) — same
            # reasoning as meetings.project_id.
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["organization_id", "client_id"],
            ["clients.organization_id", "clients.id"],
            name="fk_document_references_org_client_clients",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["organization_id", "meeting_id"],
            ["meetings.organization_id", "meetings.id"],
            name="fk_document_references_org_meeting_meetings",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["organization_id", "added_by"],
            ["memberships.organization_id", "memberships.user_id"],
            name="fk_document_references_org_added_by_memberships",
            ondelete="RESTRICT",
        ),
        Index("ix_document_references_org_project", "organization_id", "project_id"),
        Index("ix_document_references_org_client", "organization_id", "client_id"),
        Index("ix_document_references_org_meeting", "organization_id", "meeting_id"),
        Index("ix_document_references_org_added_by", "organization_id", "added_by"),
    )


class RateLimitBucket(Base):
    """Fixed-window limiter, updated by one atomic `INSERT ... ON CONFLICT DO
    UPDATE` (ADR-0010) — never read-increment-write across statements."""

    __tablename__ = "rate_limit_buckets"

    key: Mapped[str] = mapped_column(sa.Text, primary_key=True)
    window_start: Mapped[datetime] = mapped_column(_TZ, nullable=False)
    count: Mapped[int] = mapped_column(nullable=False, server_default=text("0"))

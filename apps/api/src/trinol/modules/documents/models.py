from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

import sqlalchemy as sa
from sqlalchemy import Enum as PgEnum
from sqlalchemy import FetchedValue, ForeignKeyConstraint, Index, text
from sqlalchemy.orm import Mapped, mapped_column

from trinol.core.db.base import Base
from trinol.core.db.org_scoped import OrgScoped
from trinol.core.ids import uuid7

_TZ = sa.DateTime(timezone=True)


class DocumentKind(StrEnum):
    """DATABASE.md §3 (documents) leaves `kind`'s values undefined —
    invented this phase (Phase 6 plan decision 1), directly matching
    ROADMAP.md's own three non-"document references" checklist bullets
    one-to-one: Google Drive, GitHub, and "additional useful integrations"
    (`OTHER`, a catch-all). `ponytail: extend if a specific system earns
    its own icon/filter later — nothing forces more values now."""

    GOOGLE_DRIVE = "GOOGLE_DRIVE"
    GITHUB = "GITHUB"
    OTHER = "OTHER"


class DocumentReference(OrgScoped, Base):
    """DATABASE.md §3 (documents) / ADR-0012: "V1 stores external links"
    for Google Drive, extended to GitHub and other systems by the same
    reasoning (Phase 6 plan) — a plain URL-reference table, not a
    `file_objects` wrapper; no upload, no OAuth.

    Lives in its own `documents` module, not `platform` (Codex Phase 6
    Stage 2 P1): this table's own validation needs to confirm a
    `project_id`/`client_id`/`meeting_id` exists in-org, which means
    importing `work`/`crm`/`meetings` services — ARCHITECTURE.md §3's
    `platform ← everything` rule means `platform` may never import a
    domain module, only be imported by one. `documents → work/crm/
    meetings` is a new one-way edge, the same shape `finance → work/crm`
    and `meetings → work/crm` already established, not a special case.

    `project_id`/`client_id`/`meeting_id` are each independently optional
    and not mutually exclusive (Phase 6 plan decision 4) — a parent-less
    row is a legitimate general org-wide link. Not one of ADR-0011's four
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

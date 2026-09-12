from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy import FetchedValue, ForeignKeyConstraint, Index, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from trinol.core.db.base import Base
from trinol.core.db.org_scoped import OrgScoped
from trinol.core.ids import uuid7

_TZ = sa.DateTime(timezone=True)


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

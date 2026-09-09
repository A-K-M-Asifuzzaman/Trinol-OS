from __future__ import annotations

import uuid
from datetime import date, datetime
from enum import StrEnum

import sqlalchemy as sa
from sqlalchemy import (
    CheckConstraint,
    FetchedValue,
    ForeignKeyConstraint,
    Index,
    UniqueConstraint,
    text,
)
from sqlalchemy import Enum as PgEnum
from sqlalchemy.orm import Mapped, mapped_column

from trinol.core.db.base import Base
from trinol.core.db.org_scoped import OrgScoped
from trinol.core.ids import uuid7

_TZ = sa.DateTime(timezone=True)


class MeetingParticipantResponse(StrEnum):
    """DATABASE.md §3 leaves `meeting_participants.response` undefined —
    invented this phase, mirroring how every other status enum here is a
    plain StrEnum with no permission weight of its own."""

    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    TENTATIVE = "TENTATIVE"


class Meeting(OrgScoped, Base):
    """DATABASE.md §3 (meetings). ADR-0011: meetings are hard-deleted, not
    among the four soft-deleted entities — no `archived_at` here."""

    __tablename__ = "meetings"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    title: Mapped[str] = mapped_column(sa.Text, nullable=False)
    description: Mapped[str | None] = mapped_column(sa.Text, default=None)
    starts_at: Mapped[datetime] = mapped_column(_TZ, nullable=False)
    ends_at: Mapped[datetime] = mapped_column(_TZ, nullable=False)
    client_id: Mapped[uuid.UUID | None] = mapped_column(default=None)
    project_id: Mapped[uuid.UUID | None] = mapped_column(default=None)
    meeting_url: Mapped[str | None] = mapped_column(sa.Text, default=None)
    location: Mapped[str | None] = mapped_column(sa.Text, default=None)
    notes: Mapped[str | None] = mapped_column(sa.Text, default=None)
    # Deferred to a future phase (ADR-0012: Google Calendar "not justified
    # until asked") — nullable and unused until then.
    external_event_id: Mapped[str | None] = mapped_column(sa.Text, default=None)
    # Person reference -> memberships, not users (DATABASE.md §5.1).
    # Non-nullable authorship column: attribution is the point.
    created_by: Mapped[uuid.UUID] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(_TZ, server_default=text("now()"))
    # DATABASE.md §3's "timestamps" (plural) for meetings, unlike its
    # sub-resources which only get created_at. server_onupdate:
    # trg_meetings_updated_at (migration 0006) refreshes this on every
    # UPDATE — same fix Task.updated_at/Project.updated_at already apply.
    updated_at: Mapped[datetime] = mapped_column(
        _TZ, server_default=text("now()"), server_onupdate=FetchedValue()
    )

    __table_args__ = (
        # Required by composite FKs from meeting_participants,
        # meeting_decisions, meeting_actions, and a future
        # document_references.meeting_id (DATABASE.md §5.1). Redundant for
        # uniqueness alone; do not remove as dead weight.
        UniqueConstraint("organization_id", "id", name="uq_meetings_org_id"),
        ForeignKeyConstraint(
            ["organization_id", "client_id"],
            ["clients.organization_id", "clients.id"],
            name="fk_meetings_org_client_clients",
            # Nullable; clients are soft-deleted only (ADR-0011) — an
            # unexpected hard delete under a linked meeting should fail
            # loudly, same reasoning as projects.client_id.
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["organization_id", "project_id"],
            ["projects.organization_id", "projects.id"],
            name="fk_meetings_org_project_projects",
            # Nullable; projects are soft-deleted only (ADR-0011) — same
            # reasoning as tasks.project_id.
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["organization_id", "created_by"],
            ["memberships.organization_id", "memberships.user_id"],
            name="fk_meetings_org_created_by_memberships",
            # Non-nullable authorship column (DATABASE.md §5.2): RESTRICT.
            ondelete="RESTRICT",
        ),
        CheckConstraint("ends_at > starts_at", name="ck_meeting_times"),
        Index("ix_meetings_org_starts_at", "organization_id", "starts_at"),
        # fk_meetings_org_client_clients / fk_meetings_org_project_projects /
        # fk_meetings_org_created_by_memberships aren't covered by the index
        # above (DATABASE.md §1).
        Index("ix_meetings_org_client", "organization_id", "client_id"),
        Index("ix_meetings_org_project", "organization_id", "project_id"),
        Index("ix_meetings_org_created_by", "organization_id", "created_by"),
    )


class MeetingParticipant(OrgScoped, Base):
    __tablename__ = "meeting_participants"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    meeting_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    user_id: Mapped[uuid.UUID | None] = mapped_column(default=None)
    external_email: Mapped[str | None] = mapped_column(sa.Text, default=None)
    response: Mapped[MeetingParticipantResponse] = mapped_column(
        PgEnum(
            MeetingParticipantResponse,
            name="meeting_participant_response",
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        server_default=MeetingParticipantResponse.PENDING.value,
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "meeting_id"],
            ["meetings.organization_id", "meetings.id"],
            name="fk_meeting_participants_org_meeting_meetings",
            # ADR-0011: meetings are hard-deleted; a participant row
            # without its meeting is meaningless.
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["organization_id", "user_id"],
            ["memberships.organization_id", "memberships.user_id"],
            name="fk_meeting_participants_org_user_memberships",
            # DATABASE.md §5.2: nullable, but SET NULL would silently erase
            # who was invited — RESTRICT, deactivation is the supported
            # path for removing a person, not deletion.
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "(user_id IS NOT NULL) <> (external_email IS NOT NULL)",
            name="ck_meeting_participant_identity",
        ),
        Index("ix_meeting_participants_org_meeting", "organization_id", "meeting_id"),
        Index("ix_meeting_participants_org_user", "organization_id", "user_id"),
    )


class MeetingDecision(OrgScoped, Base):
    """Append-only in spirit (no `edited_at`/`updated_at`) — inherits the
    parent meeting's own edit rule, not an author-only rule (there's no
    author concept here, same reasoning task_attachments' docstring
    already gives for its own sub-resource)."""

    __tablename__ = "meeting_decisions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    meeting_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    body: Mapped[str] = mapped_column(sa.Text, nullable=False)
    # Person reference -> memberships, not users (DATABASE.md §5.1). Not
    # spelled out in DATABASE.md §5.2's ON DELETE table alongside the other
    # nullable actor columns — treated identically (RESTRICT), same shape
    # as tasks.assignee_id/leads.assigned_to.
    decided_by: Mapped[uuid.UUID | None] = mapped_column(default=None)
    created_at: Mapped[datetime] = mapped_column(_TZ, server_default=text("now()"))

    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "meeting_id"],
            ["meetings.organization_id", "meetings.id"],
            name="fk_meeting_decisions_org_meeting_meetings",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["organization_id", "decided_by"],
            ["memberships.organization_id", "memberships.user_id"],
            name="fk_meeting_decisions_org_decided_by_memberships",
            ondelete="RESTRICT",
        ),
        Index("ix_meeting_decisions_org_meeting", "organization_id", "meeting_id"),
        Index("ix_meeting_decisions_org_decided_by", "organization_id", "decided_by"),
    )


class MeetingAction(OrgScoped, Base):
    """`task_id` is set exactly once, by
    `meetings.services.meeting_action_service.promote_action`
    (ARCHITECTURE.md §3) — never client-settable via a PATCH."""

    __tablename__ = "meeting_actions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    meeting_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    description: Mapped[str] = mapped_column(sa.Text, nullable=False)
    # Person reference -> memberships, not users (DATABASE.md §5.1). Same
    # gap-fill as MeetingDecision.decided_by above.
    owner_id: Mapped[uuid.UUID | None] = mapped_column(default=None)
    due_date: Mapped[date | None] = mapped_column(sa.Date, default=None)
    task_id: Mapped[uuid.UUID | None] = mapped_column(default=None)
    created_at: Mapped[datetime] = mapped_column(_TZ, server_default=text("now()"))

    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "meeting_id"],
            ["meetings.organization_id", "meetings.id"],
            name="fk_meeting_actions_org_meeting_meetings",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["organization_id", "owner_id"],
            ["memberships.organization_id", "memberships.user_id"],
            name="fk_meeting_actions_org_owner_memberships",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["organization_id", "task_id"],
            ["tasks.organization_id", "tasks.id"],
            name="fk_meeting_actions_org_task_tasks",
            # Tasks are hard-deleted (ADR-0011). No DB-level uniqueness on
            # task_id this phase — the service-level row-lock guard in
            # promote_action is the actual double-promotion guard.
            # `ponytail: add a partial unique index if a real race ever
            # produces a duplicate.`
            ondelete="RESTRICT",
        ),
        Index("ix_meeting_actions_org_meeting", "organization_id", "meeting_id"),
        Index("ix_meeting_actions_org_owner", "organization_id", "owner_id"),
        Index("ix_meeting_actions_org_task", "organization_id", "task_id"),
    )

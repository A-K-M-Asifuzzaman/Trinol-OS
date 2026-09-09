from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

import sqlalchemy as sa
from sqlalchemy import (
    CheckConstraint,
    FetchedValue,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    UniqueConstraint,
    text,
)
from sqlalchemy import Enum as PgEnum
from sqlalchemy.dialects.postgresql import INET
from sqlalchemy.orm import Mapped, mapped_column

from trinol.core.db.base import Base
from trinol.core.db.org_scoped import OrgScoped
from trinol.core.ids import uuid7

_TZ = sa.DateTime(timezone=True)


class ClientStatus(StrEnum):
    """DATABASE.md §3 lists `status` on `clients` with no enum values
    spelled out (unlike `leads.stage`/`source`) — kept to the minimum that
    distinguishes a client still being worked with from one that isn't,
    without duplicating what `archived_at` (ADR-0011) already covers for
    the fully-inactive case."""

    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class LeadSource(StrEnum):
    WEBSITE = "WEBSITE"
    FACEBOOK = "FACEBOOK"
    LINKEDIN = "LINKEDIN"
    REFERRAL = "REFERRAL"
    EMAIL = "EMAIL"
    PHONE = "PHONE"
    OTHER = "OTHER"


class LeadStage(StrEnum):
    NEW = "NEW"
    CONTACTED = "CONTACTED"
    MEETING = "MEETING"
    PROPOSAL = "PROPOSAL"
    NEGOTIATION = "NEGOTIATION"
    WON = "WON"
    LOST = "LOST"


class Client(OrgScoped, Base):
    """DATABASE.md §3 (crm)."""

    __tablename__ = "clients"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    name: Mapped[str] = mapped_column(sa.Text, nullable=False)
    company: Mapped[str | None] = mapped_column(sa.Text, default=None)
    email: Mapped[str | None] = mapped_column(sa.Text, default=None)
    phone: Mapped[str | None] = mapped_column(sa.Text, default=None)
    website: Mapped[str | None] = mapped_column(sa.Text, default=None)
    address: Mapped[str | None] = mapped_column(sa.Text, default=None)
    notes: Mapped[str | None] = mapped_column(sa.Text, default=None)
    status: Mapped[ClientStatus] = mapped_column(
        PgEnum(ClientStatus, name="client_status", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        server_default=ClientStatus.ACTIVE.value,
    )
    # Person reference -> memberships, not users (DATABASE.md §5.1).
    # Nullable: a client isn't required to have an assigned owner at
    # creation (unlike Project.owner_id, which always has one).
    owner_id: Mapped[uuid.UUID | None] = mapped_column(default=None)
    # Soft delete (ADR-0011): clients are archived, never hard-deleted by a
    # product flow.
    archived_at: Mapped[datetime | None] = mapped_column(_TZ, default=None)
    created_at: Mapped[datetime] = mapped_column(_TZ, server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(
        _TZ, server_default=text("now()"), server_onupdate=FetchedValue()
    )

    __table_args__ = (
        # Required by composite FKs from projects.client_id,
        # leads.converted_client_id, and future-phase meetings/income/
        # invoices/document_references.client_id (DATABASE.md §5.1).
        # Redundant for uniqueness alone; do not remove as dead weight.
        UniqueConstraint("organization_id", "id", name="uq_clients_org_id"),
        ForeignKeyConstraint(
            ["organization_id", "owner_id"],
            ["memberships.organization_id", "memberships.user_id"],
            name="fk_clients_org_owner_memberships",
            ondelete="RESTRICT",
        ),
        Index("ix_clients_org_owner", "organization_id", "owner_id"),
    )


class Lead(OrgScoped, Base):
    """DATABASE.md §3 (crm). `board_position` mirrors `Task`'s fractional-
    indexing sort key exactly, for the same Kanban-drag reason (`ponytail:
    fractional indexing, rebalance job if precision is ever exhausted` —
    same accepted debt Phase 2 logged for tasks)."""

    __tablename__ = "leads"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    name: Mapped[str] = mapped_column(sa.Text, nullable=False)
    company: Mapped[str | None] = mapped_column(sa.Text, default=None)
    email: Mapped[str | None] = mapped_column(sa.Text, default=None)
    phone: Mapped[str | None] = mapped_column(sa.Text, default=None)
    source: Mapped[LeadSource] = mapped_column(
        PgEnum(LeadSource, name="lead_source", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )
    service: Mapped[str | None] = mapped_column(sa.Text, default=None)
    # DATABASE.md §1 / ADR-0007: NUMERIC in Postgres, Decimal in Python —
    # never float, anywhere in the stack.
    estimated_value: Mapped[Decimal | None] = mapped_column(sa.Numeric(14, 2), default=None)
    currency: Mapped[str] = mapped_column(sa.Text, nullable=False, server_default="USD")
    stage: Mapped[LeadStage] = mapped_column(
        PgEnum(LeadStage, name="lead_stage", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        server_default=LeadStage.NEW.value,
    )
    # Person reference -> memberships, not users (DATABASE.md §5.1).
    assigned_to: Mapped[uuid.UUID | None] = mapped_column(default=None)
    next_follow_up: Mapped[date | None] = mapped_column(sa.Date, default=None)
    notes: Mapped[str | None] = mapped_column(sa.Text, default=None)
    # Set only by work.services.lead_conversion_service.convert_lead
    # (ARCHITECTURE.md §3) — never client-settable via LeadUpdateRequest.
    converted_client_id: Mapped[uuid.UUID | None] = mapped_column(default=None)
    converted_at: Mapped[datetime | None] = mapped_column(_TZ, default=None)
    lost_reason: Mapped[str | None] = mapped_column(sa.Text, default=None)
    board_position: Mapped[Decimal] = mapped_column(sa.Numeric, nullable=False, server_default="0")
    # Soft delete (ADR-0011): leads are archived, never hard-deleted by a
    # product flow.
    archived_at: Mapped[datetime | None] = mapped_column(_TZ, default=None)
    created_at: Mapped[datetime] = mapped_column(_TZ, server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(
        _TZ, server_default=text("now()"), server_onupdate=FetchedValue()
    )

    __table_args__ = (
        # Required by lead_stage_events.lead_id and
        # contact_submissions.lead_id's composite FKs (DATABASE.md §5.1).
        UniqueConstraint("organization_id", "id", name="uq_leads_org_id"),
        ForeignKeyConstraint(
            ["organization_id", "assigned_to"],
            ["memberships.organization_id", "memberships.user_id"],
            name="fk_leads_org_assigned_to_memberships",
            # DATABASE.md §5.2: nullable, but SET NULL would silently erase
            # who owned the work — RESTRICT, deactivation is the supported
            # path for removing a person, not deletion.
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["organization_id", "converted_client_id"],
            ["clients.organization_id", "clients.id"],
            name="fk_leads_org_converted_client_clients",
            # Clients are archived, never hard-deleted (ADR-0011) — an
            # unexpected hard delete under a converted lead should fail
            # loudly, same reasoning as tasks.project_id -> projects.
            ondelete="RESTRICT",
        ),
        CheckConstraint("email IS NOT NULL OR phone IS NOT NULL", name="ck_lead_contact"),
        Index("ix_leads_org_stage", "organization_id", "stage"),
        Index("ix_leads_org_followup", "organization_id", "next_follow_up"),
        # fk_leads_org_assigned_to_memberships isn't covered by either index
        # above (DATABASE.md §1). Same for
        # fk_leads_org_converted_client_clients.
        Index("ix_leads_org_assigned_to", "organization_id", "assigned_to"),
        Index("ix_leads_org_converted_client", "organization_id", "converted_client_id"),
    )


class LeadStageEvent(OrgScoped, Base):
    """DATABASE.md §3 (crm). Pipeline history; written in the same
    transaction as the stage change (lead_service.change_lead_stage) —
    never archived, never edited, a history table like task_comments'
    sibling in spirit but append-only by convention, not by DB grant
    (unlike activity_events, which enforces it at the grant level)."""

    __tablename__ = "lead_stage_events"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    lead_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    from_stage: Mapped[LeadStage | None] = mapped_column(
        PgEnum(LeadStage, name="lead_stage", create_type=False), default=None
    )
    to_stage: Mapped[LeadStage] = mapped_column(
        PgEnum(LeadStage, name="lead_stage", create_type=False), nullable=False
    )
    # Exception to the "references reach memberships, not users" rule
    # (DATABASE.md §5.1, same exception activity_events.actor_id/
    # invitations.invited_by already document): history must survive the
    # actor leaving the org.
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    created_at: Mapped[datetime] = mapped_column(_TZ, server_default=text("now()"))

    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "lead_id"],
            ["leads.organization_id", "leads.id"],
            name="fk_lead_stage_events_org_lead_leads",
            ondelete="CASCADE",
        ),
        Index("ix_lead_stage_events_org_lead", "organization_id", "lead_id"),
    )


class ContactSubmission(OrgScoped, Base):
    """DATABASE.md §3 (crm). Raw inbound record from the unauthenticated
    `POST /api/public/contact` — kept even when the lead is later deleted.
    `organization_id` here is resolved once at startup from
    `settings.public_contact_org_slug` (SECURITY.md §5), never from a
    session — this is the one org-scoped write with no session behind it."""

    __tablename__ = "contact_submissions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    name: Mapped[str] = mapped_column(sa.Text, nullable=False)
    email: Mapped[str] = mapped_column(sa.Text, nullable=False)
    phone: Mapped[str | None] = mapped_column(sa.Text, default=None)
    company: Mapped[str | None] = mapped_column(sa.Text, default=None)
    service: Mapped[str | None] = mapped_column(sa.Text, default=None)
    budget: Mapped[str | None] = mapped_column(sa.Text, default=None)
    message: Mapped[str] = mapped_column(sa.Text, nullable=False)
    ip: Mapped[str | None] = mapped_column(INET, default=None)
    user_agent: Mapped[str | None] = mapped_column(sa.Text, default=None)
    reference_number: Mapped[str] = mapped_column(sa.Text, nullable=False)
    lead_id: Mapped[uuid.UUID | None] = mapped_column(default=None)
    spam_score: Mapped[Decimal | None] = mapped_column(sa.Numeric(5, 2), default=None)
    created_at: Mapped[datetime] = mapped_column(_TZ, server_default=text("now()"))

    __table_args__ = (
        UniqueConstraint(
            "organization_id", "reference_number", name="uq_contact_submissions_org_reference"
        ),
        ForeignKeyConstraint(
            ["organization_id", "lead_id"],
            ["leads.organization_id", "leads.id"],
            name="fk_contact_submissions_org_lead_leads",
            # Nullable (a spam/rejected submission has no lead). RESTRICT,
            # not SET NULL: on a composite FK, Postgres nulls every
            # referencing column including organization_id, which is NOT
            # NULL here (the exact bug class Phase 2 fixed twice) — moot in
            # practice, since a lead is never hard-deleted by any product
            # flow (ADR-0011).
            ondelete="RESTRICT",
        ),
        Index("ix_contact_submissions_org_lead", "organization_id", "lead_id"),
    )

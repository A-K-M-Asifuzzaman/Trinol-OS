from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

import sqlalchemy as sa
from sqlalchemy import Enum as PgEnum
from sqlalchemy import FetchedValue, ForeignKey, ForeignKeyConstraint, Index, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import CITEXT, INET
from sqlalchemy.orm import Mapped, mapped_column

from trinol.core.authz.permissions import Role
from trinol.core.db.base import Base
from trinol.core.db.org_scoped import OrgScoped
from trinol.core.ids import uuid7

_TZ = sa.DateTime(timezone=True)


class AuthProvider(StrEnum):
    PASSWORD = "PASSWORD"
    GOOGLE = "GOOGLE"


class MembershipStatus(StrEnum):
    ACTIVE = "ACTIVE"
    ON_LEAVE = "ON_LEAVE"
    INACTIVE = "INACTIVE"


# `Role` (not a separate MembershipRole) lives in core/authz/permissions.py —
# one enum for the concept, shared by the DB column and the permission map.
# Defined once, reused by both Membership.role and Invitation.role, so
# SQLAlchemy treats them as the same native Postgres enum type rather than
# trying to create "membership_role" twice.
_membership_role_type = PgEnum(
    Role, name="membership_role", values_callable=lambda e: [m.value for m in e]
)


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    name: Mapped[str] = mapped_column(sa.Text, nullable=False)
    slug: Mapped[str] = mapped_column(sa.Text, unique=True, nullable=False)
    # Restored now that file_objects exists (Stage 6) — deferred since
    # Stage 1/3 for exactly that reason.
    logo_file_id: Mapped[uuid.UUID | None] = mapped_column(default=None)
    created_at: Mapped[datetime] = mapped_column(_TZ, server_default=text("now()"))
    # server_onupdate: trg_organizations_updated_at (migration 0001) already
    # refreshes this on every UPDATE; no route updates Organization yet, so
    # this was harmlessly wrong until now — fixed proactively while this
    # class is open anyway, same trigger-refresh fix Codex's Phase 2 review
    # applied to Project/Task/TaskComment, before a future org-settings
    # route could independently rediscover it.
    updated_at: Mapped[datetime] = mapped_column(
        _TZ, server_default=text("now()"), server_onupdate=FetchedValue()
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["id", "logo_file_id"],
            ["file_objects.organization_id", "file_objects.id"],
            name="fk_organizations_id_logo_file_id_file_objects",
            # DATABASE.md §3: NOT "SET NULL" — on a composite FK, Postgres
            # nulls every referencing column, and `id` is this table's
            # primary key, which can never be null. The service clears
            # logo_file_id itself before deleting a file_objects row
            # currently in use as a logo; a missing logo is still meant to
            # be cosmetic, just not enforced by the FK's own cascade.
            ondelete="RESTRICT",
        ),
    )


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    firebase_uid: Mapped[str] = mapped_column(sa.Text, unique=True, nullable=False)
    email: Mapped[str] = mapped_column(CITEXT, unique=True, nullable=False)
    auth_provider: Mapped[AuthProvider] = mapped_column(
        PgEnum(AuthProvider, name="auth_provider", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )
    full_name: Mapped[str] = mapped_column(sa.Text, nullable=False)
    avatar_url: Mapped[str | None] = mapped_column(sa.Text, default=None)
    last_login_at: Mapped[datetime | None] = mapped_column(_TZ, default=None)
    created_at: Mapped[datetime] = mapped_column(_TZ, server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(_TZ, server_default=text("now()"))


class Membership(OrgScoped, Base):
    __tablename__ = "memberships"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    role: Mapped[Role] = mapped_column(_membership_role_type, nullable=False)
    job_title: Mapped[str | None] = mapped_column(sa.Text, default=None)
    status: Mapped[MembershipStatus] = mapped_column(
        PgEnum(
            MembershipStatus,
            name="membership_status",
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        server_default=MembershipStatus.ACTIVE.value,
    )
    joined_at: Mapped[datetime] = mapped_column(_TZ, server_default=text("now()"))
    created_at: Mapped[datetime] = mapped_column(_TZ, server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(_TZ, server_default=text("now()"))

    __table_args__ = (
        UniqueConstraint("organization_id", "user_id", name="uq_membership_org_user"),
        # No separate organization_id index: the constraint above already
        # starts with it (DATABASE.md §1).
    )


class Invitation(OrgScoped, Base):
    __tablename__ = "invitations"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    email: Mapped[str] = mapped_column(CITEXT, nullable=False)
    role: Mapped[Role] = mapped_column(_membership_role_type, nullable=False)
    token_hash: Mapped[str] = mapped_column(sa.Text, unique=True, nullable=False)
    # Exception to the "references reach memberships, not users" rule
    # (DATABASE.md §5.1): the inviter may not be a member of this org yet.
    invited_by: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(_TZ, nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(_TZ, default=None)

    __table_args__ = (Index("ix_invitations_organization_id", "organization_id"),)


class Session(OrgScoped, Base):
    __tablename__ = "sessions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    # No single-column FK here: the composite one below covers organization_id
    # + user_id together (DATABASE.md §5.1 — "sessions follows the same rule").
    user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    token_hash: Mapped[str] = mapped_column(sa.Text, unique=True, nullable=False)
    # Plaintext, not hashed like token_hash: AUTH.md §6 requires the raw
    # value back from GET /api/v1/auth/session, impossible from a one-way
    # hash. Security here is same-origin-policy-based (a cross-site page
    # can't read the response or set X-CSRF-Token), not secrecy-at-rest —
    # standard for double-submit CSRF tokens (see migration 0002).
    csrf_token: Mapped[str] = mapped_column(sa.Text, nullable=False)
    user_agent: Mapped[str | None] = mapped_column(sa.Text, default=None)
    ip: Mapped[str | None] = mapped_column(INET, default=None)
    expires_at: Mapped[datetime] = mapped_column(_TZ, nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(_TZ, server_default=text("now()"))
    revoked_at: Mapped[datetime | None] = mapped_column(_TZ, default=None)

    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "user_id"],
            ["memberships.organization_id", "memberships.user_id"],
            name="fk_sessions_org_user_memberships",
            ondelete="CASCADE",
        ),
        Index("ix_sessions_organization_id", "organization_id"),
    )

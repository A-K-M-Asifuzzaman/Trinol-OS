from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from trinol.core.authz.permissions import Role
from trinol.core.db.org_session import OrgSession
from trinol.core.deps import get_settings
from trinol.core.errors import ConflictError, ForbiddenError, NotFoundError
from trinol.core.ids import uuid7
from trinol.modules.identity.models import (
    Invitation,
    Membership,
    Organization,
    User,
)
from trinol.modules.identity.services.organization_lock import lock_organization
from trinol.platform.activity import record
from trinol.platform.email.protocol import EmailMessage
from trinol.platform.email.render import render_invitation_email

# Matches the existing session/invitation-provisioning test fixture default
# (AUTH.md's invited path) rather than inventing a second lifetime elsewhere.
_INVITATION_LIFETIME = timedelta(days=7)


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _ensure_actor_is_admin(actor: Membership, organization_id: uuid.UUID) -> None:
    """Same defense-in-depth reasoning as membership_service's
    _ensure_actor_can_act: the route-level Permission.MEMBER_INVITE/TEAM_READ
    gate is the only other protection either function here has."""
    if actor.organization_id != organization_id:
        raise ForbiddenError("Actor does not belong to this organization")
    if actor.role not in (Role.ADMIN, Role.OWNER):
        raise ForbiddenError("Insufficient role to manage invitations")


@dataclass(frozen=True, slots=True)
class CreatedInvitation:
    invitation: Invitation
    email_message: EmailMessage


@dataclass(frozen=True, slots=True)
class InvitationPreview:
    organization_name: str
    role: Role
    email: str
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class InvitationList:
    items: list[Invitation]
    total: int


async def create_invitation(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    actor: Membership,
    email: str,
    role: Role,
) -> CreatedInvitation:
    _ensure_actor_is_admin(actor, organization_id)
    if role in (Role.OWNER, Role.ADMIN) and actor.role != Role.OWNER:
        raise ForbiddenError("Only an OWNER may invite an OWNER or ADMIN")

    org_session = OrgSession(db, organization_id=organization_id)
    now = datetime.now(UTC)

    await lock_organization(db, organization_id)
    # Everything from here runs while holding the FOR UPDATE lock taken
    # above (same pattern as membership_service's guards, see
    # organization_lock.py) — closes a real race Codex's Stage 8 review
    # found: two concurrent requests for the same org+email could both pass
    # the "no open invitation exists" check below and both insert. The
    # second caller now blocks until the first's commit or rollback, then
    # re-reads a fresh view of the world.
    try:
        existing_user_result = await db.execute(select(User).where(User.email == email))
        existing_user = existing_user_result.scalar_one_or_none()
        if existing_user is not None:
            # Any membership row, not just ACTIVE: an INACTIVE/ON_LEAVE
            # membership means this person already has a User + Membership
            # row, so a fresh invitation can never be consumed —
            # _resolve_or_provision_user's "existing user" branch returns
            # immediately without ever looking at invitations (that's a
            # returning login, not a re-provisioning), and exchange_session
            # then rejects on the existing membership's own status. Inviting
            # them again would only create a dead row. Reactivating a former
            # member needs an explicit path, not an invitation (see
            # ROADMAP.md's technical debt ledger).
            membership_result = await db.execute(
                org_session.select(Membership).where(Membership.user_id == existing_user.id)
            )
            if membership_result.scalar_one_or_none() is not None:
                raise ConflictError("This person already has a membership in this organization")

        open_invitation_result = await db.execute(
            org_session.select(Invitation).where(
                Invitation.email == email,
                Invitation.accepted_at.is_(None),
                Invitation.expires_at > now,
            )
        )
        if open_invitation_result.scalars().first() is not None:
            raise ConflictError("An open invitation already exists for this email")

        inviter_result = await db.execute(select(User).where(User.id == actor.user_id))
        inviter = inviter_result.scalar_one()
        org_result = await db.execute(
            select(Organization).where(Organization.id == organization_id)
        )
        organization = org_result.scalar_one()

        raw_token = secrets.token_urlsafe(32)
        invitation = Invitation(
            id=uuid7(),
            email=email,
            role=role,
            token_hash=_hash(raw_token),
            invited_by=actor.user_id,
            expires_at=now + _INVITATION_LIFETIME,
        )
        org_session.add(invitation)
        await db.flush()

        await record(
            db,
            organization_id=organization_id,
            event="invitation.created",
            entity_type="invitation",
            entity_id=invitation.id,
            actor_id=actor.user_id,
            metadata={"email": email, "role": role.value},
            audit=True,
        )

        settings = get_settings()
        html_body, text_body = render_invitation_email(
            inviter_name=inviter.full_name,
            organization_name=organization.name,
            role=role.value,
            accept_url=f"{settings.app_origin}/join?token={raw_token}",
            expires_at=invitation.expires_at.date().isoformat(),
        )
        # The route sends this via BackgroundTasks *after* db.commit() below
        # (EMAIL.md §3) — this function only builds the message, never sends it.
        email_message = EmailMessage(
            to=email,
            subject=f"You've been invited to join {organization.name} on Trinol OS",
            html_body=html_body,
            text_body=text_body,
        )

        await db.commit()
        return CreatedInvitation(invitation=invitation, email_message=email_message)
    except Exception:
        await db.rollback()
        raise


async def list_open_invitations(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    actor: Membership,
    limit: int = 50,
    offset: int = 0,
) -> InvitationList:
    _ensure_actor_is_admin(actor, organization_id)
    now = datetime.now(UTC)
    # ADR-0005's "open" list is unaccepted *and* unexpired — an expired row
    # is dead exactly like an accepted one, and listing it (or letting it
    # count toward pagination) misrepresents what an ADMIN can actually act
    # on. Matches create_invitation's own duplicate-open-invitation filter.
    open_filter = (
        Invitation.accepted_at.is_(None),
        Invitation.expires_at > now,
    )

    total_result = await db.execute(
        select(func.count())
        .select_from(Invitation)
        .where(Invitation.organization_id == organization_id, *open_filter)
    )
    total = total_result.scalar_one()

    org_session = OrgSession(db, organization_id=organization_id)
    result = await db.execute(
        org_session.select(Invitation)
        .where(*open_filter)
        # Invitation has no created_at column; id is a uuid7, which sorts by
        # creation time on its own (core/ids.py).
        .order_by(Invitation.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return InvitationList(items=list(result.scalars().all()), total=total)


async def get_invitation_preview(db: AsyncSession, *, raw_token: str) -> InvitationPreview:
    """Public, unscoped (DATABASE.md §5.1's documented escape hatch, same
    pattern as session_service's pre-org-context lookups): the invitation-
    landing page renders this before the user ever signs into Firebase
    (decision 3, Phase 1 plan). Mutates nothing."""
    result = await db.execute(
        OrgSession.unscoped(select(Invitation).where(Invitation.token_hash == _hash(raw_token)))
    )
    invitation = result.scalar_one_or_none()
    if (
        invitation is None
        or invitation.accepted_at is not None
        or invitation.expires_at < datetime.now(UTC)
    ):
        raise NotFoundError("Invitation not found")

    org_result = await db.execute(
        select(Organization).where(Organization.id == invitation.organization_id)
    )
    organization = org_result.scalar_one()

    return InvitationPreview(
        organization_name=organization.name,
        role=invitation.role,
        email=invitation.email,
        expires_at=invitation.expires_at,
    )

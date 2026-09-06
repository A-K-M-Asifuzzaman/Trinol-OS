from __future__ import annotations

import hashlib
import logging
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from trinol.core.db.org_session import OrgSession
from trinol.core.errors import ForbiddenError, UnauthorizedError
from trinol.core.ids import uuid7
from trinol.modules.identity.identity_verifier import (
    IdentityVerificationError,
    IdentityVerifier,
    VerifiedIdentity,
)
from trinol.modules.identity.models import (
    AuthProvider,
    Invitation,
    Membership,
    MembershipStatus,
    Session,
    User,
)
from trinol.platform.activity import record
from trinol.platform.rate_limit import check_rate_limit

logger = logging.getLogger(__name__)

# Backstop against a runaway client hammering the DB, not the primary defense
# against credential-guessing — that's Firebase's own throttling (AUTH.md
# §5). Deliberately generous; a real user never gets near it.
_EXCHANGE_RATE_LIMIT = 30
_EXCHANGE_RATE_WINDOW = timedelta(minutes=1)

_SESSION_ABSOLUTE_LIFETIME = timedelta(days=30)  # AUTH.md §3
SESSION_IDLE_TIMEOUT = timedelta(days=7)  # AUTH.md §3
LAST_SEEN_REFRESH_INTERVAL = timedelta(minutes=5)  # AUTH.md §3


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def get_session_by_token_hash(db: AsyncSession, token_hash: str) -> Session | None:
    """Shared by deps.py (get_current_session) and core/security/csrf.py —
    both need to resolve a session from a raw cookie value before its
    organization is known, hence unscoped (DATABASE.md §5.1's documented
    escape hatch, same as the membership/invitation lookups below)."""
    result = await db.execute(
        OrgSession.unscoped(select(Session).where(Session.token_hash == token_hash))
    )
    return result.scalar_one_or_none()


def _auth_provider_for(sign_in_provider: str) -> AuthProvider:
    return AuthProvider.GOOGLE if sign_in_provider == "google.com" else AuthProvider.PASSWORD


@dataclass(frozen=True, slots=True)
class ExchangeResult:
    session_token: str
    session: Session
    user: User
    membership: Membership


async def exchange_session(
    db: AsyncSession,
    *,
    verifier: IdentityVerifier,
    id_token: str,
    ip: str | None,
    user_agent: str | None,
) -> ExchangeResult:
    """AUTH.md §5 / ADR-0013's login flow, steps 1-5. Step 6 (browser signs
    out of the Firebase SDK) is client-side, not this function's concern.

    AUTH.md §5: "a rejection at step 3 or 4" writes an is_audit event —
    caveat found while implementing it: activity_events.organization_id is
    NOT NULL, so that's only possible where an organization is actually
    determinable (an invitation names one; an inactive membership names the
    org it's inactive in). A truly unknown identity with no invitation and no
    membership anywhere has nowhere to attach an event to — logged instead,
    not silently dropped.
    """
    await check_rate_limit(
        db,
        key=f"auth_session_exchange:{ip or 'unknown'}",
        window=_EXCHANGE_RATE_WINDOW,
        limit=_EXCHANGE_RATE_LIMIT,
    )
    # Commits *only* the rate-limit counter now, so it survives even if the
    # code below raises for an unrelated reason (bad token, no invitation,
    # ...) — otherwise the request handler's rollback would undo the count
    # along with everything else, and a rejected caller would never actually
    # be throttled no matter how many times they tried.
    await db.commit()

    try:
        identity = await verifier.verify(id_token)
    except IdentityVerificationError as exc:
        raise UnauthorizedError("Invalid or expired identity token") from exc

    if not identity.email_verified:
        raise ForbiddenError("Email address is not verified")

    user = await _resolve_or_provision_user(db, identity, ip=ip)

    # Unscoped deliberately: at this point we don't yet know which org this
    # user belongs to — discovering that IS this query (DATABASE.md §5.1's
    # documented escape hatch). V1 has one org, so at most one row comes
    # back; a future multi-org account would need an org-picker step here.
    # Any status, not just ACTIVE: an inactive membership still names an
    # organization to attribute a step-4 rejection's audit event to, which a
    # status-filtered query would have thrown away before we could see it.
    result = await db.execute(
        OrgSession.unscoped(select(Membership).where(Membership.user_id == user.id))
    )
    membership = result.scalars().first()
    if membership is None:
        logger.warning(
            "auth exchange rejected: no membership for this account",
            extra={"user_id": str(user.id), "ip": ip},
        )
        raise ForbiddenError("No active membership for this account")
    if membership.status != MembershipStatus.ACTIVE:
        await record(
            db,
            organization_id=membership.organization_id,
            event="auth.exchange.rejected",
            entity_type="user",
            entity_id=user.id,
            actor_id=user.id,
            metadata={"reason": "membership_inactive", "user_agent": user_agent},
            audit=True,
            ip=ip,
        )
        await db.commit()
        raise ForbiddenError("No active membership for this account")

    now = datetime.now(UTC)
    token = secrets.token_urlsafe(32)
    csrf_token = secrets.token_urlsafe(32)

    org_session = OrgSession(db, organization_id=membership.organization_id)
    session_row = Session(
        id=uuid7(),
        user_id=user.id,
        token_hash=_hash(token),
        csrf_token=csrf_token,
        user_agent=user_agent,
        ip=ip,
        expires_at=now + _SESSION_ABSOLUTE_LIFETIME,
        last_seen_at=now,
    )
    org_session.add(session_row)

    user.last_login_at = now
    await record(
        db,
        organization_id=membership.organization_id,
        event="auth.session.created",
        entity_type="user",
        entity_id=user.id,
        actor_id=user.id,
        metadata={"user_agent": user_agent} if user_agent else None,
        audit=True,
        ip=ip,
    )
    await db.commit()

    return ExchangeResult(
        session_token=token, session=session_row, user=user, membership=membership
    )


async def revoke_session(db: AsyncSession, session: Session) -> None:
    """AUTH.md §3: logout revokes the current session."""
    session.revoked_at = datetime.now(UTC)
    await db.commit()


async def revoke_all_sessions(db: AsyncSession, user_id: uuid.UUID) -> None:
    """AUTH.md §3: "log out everywhere" — every session for this user,
    unscoped deliberately. A future multi-org account's sessions in other
    organizations must be revoked too, not just the current one."""
    now = datetime.now(UTC)
    await db.execute(
        OrgSession.unscoped(
            update(Session)
            .where(Session.user_id == user_id, Session.revoked_at.is_(None))
            .values(revoked_at=now)
        )
    )
    await db.commit()


async def revoke_org_sessions(
    db: AsyncSession, *, organization_id: uuid.UUID, user_id: uuid.UUID
) -> None:
    """RBAC.md §5 guard 5: a role change or removal takes effect immediately
    by revoking the target's sessions — scoped to just this organization,
    unlike revoke_all_sessions (logout everywhere), which deliberately spans
    every organization a user belongs to. A role change in org A has nothing
    to do with that same user's session in org B.

    Deliberately does NOT commit, unlike its siblings above: this is always a
    sub-step inside change_role/remove_member's larger transaction, not a
    standalone operation. It used to commit here, which persisted the role
    change (already autoflushed) and released the organization's FOR UPDATE
    lock before guard 6's audit event was even written — if that write or the
    caller's own final commit then failed, the business mutation was already
    durably committed with no audit record, breaking ADR-0006's same-
    transaction guarantee. The caller's commit is the only one now.
    """
    now = datetime.now(UTC)
    await db.execute(
        update(Session)
        .where(
            Session.organization_id == organization_id,
            Session.user_id == user_id,
            Session.revoked_at.is_(None),
        )
        .values(revoked_at=now)
    )


async def _resolve_or_provision_user(
    db: AsyncSession, identity: VerifiedIdentity, *, ip: str | None
) -> User:
    result = await db.execute(select(User).where(User.firebase_uid == identity.firebase_uid))
    user = result.scalar_one_or_none()

    if user is not None:
        # ADR-0013: email is a refreshed cache, not the join key. Provider
        # and profile fields only overwrite when Firebase actually gave us a
        # new value, so a password sign-in after a Google one doesn't blank
        # out a name/photo Google previously supplied.
        user.email = identity.email
        user.auth_provider = _auth_provider_for(identity.sign_in_provider)
        if identity.full_name:
            user.full_name = identity.full_name
        if identity.avatar_url:
            user.avatar_url = identity.avatar_url
        return user

    # Unknown firebase_uid: only proceeds if there's an open invitation for
    # this verified email (ADR-0013 "Provisioning"). No account is ever
    # auto-created without one.
    invitation_result = await db.execute(
        OrgSession.unscoped(
            select(Invitation)
            .where(Invitation.email == identity.email, Invitation.accepted_at.is_(None))
            .with_for_update()
        )
    )
    invitation = invitation_result.scalars().first()
    if invitation is None:
        # AUTH.md §5 step 3, but genuinely no organization to attach an
        # is_audit event to (activity_events.organization_id is NOT NULL) —
        # logged instead of silently dropped.
        logger.warning(
            "auth exchange rejected: unknown identity, no open invitation",
            extra={"firebase_uid": identity.firebase_uid, "email": identity.email, "ip": ip},
        )
        raise ForbiddenError("No account or open invitation for this identity")
    if invitation.expires_at < datetime.now(UTC):
        await record(
            db,
            organization_id=invitation.organization_id,
            event="auth.exchange.rejected",
            entity_type="invitation",
            entity_id=invitation.id,
            metadata={"reason": "invitation_expired", "email": identity.email},
            audit=True,
            ip=ip,
        )
        await db.commit()
        raise ForbiddenError("Invitation has expired")

    user = User(
        id=uuid7(),
        firebase_uid=identity.firebase_uid,
        email=identity.email,
        auth_provider=_auth_provider_for(identity.sign_in_provider),
        full_name=identity.full_name or identity.email.split("@")[0],
        avatar_url=identity.avatar_url,
    )
    db.add(user)
    await db.flush()

    org_session = OrgSession(db, organization_id=invitation.organization_id)
    membership = Membership(
        id=uuid7(),
        user_id=user.id,
        role=invitation.role,
        status=MembershipStatus.ACTIVE,
    )
    org_session.add(membership)

    invitation.accepted_at = datetime.now(UTC)

    await db.flush()
    return user

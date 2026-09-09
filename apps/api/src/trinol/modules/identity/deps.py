from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from trinol.core.db.engine import get_db_session
from trinol.core.deps import get_settings
from trinol.core.errors import UnauthorizedError
from trinol.modules.identity.e2e_verifier import E2EIdentityVerifier
from trinol.modules.identity.firebase_verifier import FirebaseIdentityVerifier
from trinol.modules.identity.identity_verifier import IdentityVerifier
from trinol.modules.identity.models import Membership, MembershipStatus, Session
from trinol.modules.identity.services.session_service import (
    LAST_SEEN_REFRESH_INTERVAL,
    SESSION_IDLE_TIMEOUT,
    get_session_by_token_hash,
)

_verifier: IdentityVerifier | None = None


def get_identity_verifier() -> IdentityVerifier:
    """Overridden in tests via `app.dependency_overrides` with a
    `FakeIdentityVerifier` (ADR-0013: tests must not call Firebase).

    Stage 11 (Playwright E2E): `E2EIdentityVerifier` only when
    `e2e_test_mode` is on *and* `app_env` isn't production — checked here,
    not just left to the settings default, so a misconfigured production
    deployment can never honor the flag even if it's accidentally set."""
    global _verifier
    if _verifier is None:
        settings = get_settings()
        if settings.e2e_test_mode and settings.app_env != "production":
            _verifier = E2EIdentityVerifier()
        else:
            _verifier = FirebaseIdentityVerifier()
    return _verifier


async def get_current_session(
    request: Request, db: AsyncSession = Depends(get_db_session)
) -> Session:
    """Resolves and validates the session cookie (AUTH.md §2-3). Raises 401
    for: no cookie, unknown token, revoked, or expired (idle or absolute).

    Also does the throttled last_seen_at refresh here, since this is the one
    place every authenticated request already passes through — AUTH.md §3:
    "refreshed at most once per 5 minutes to avoid a write on every request."
    """
    settings = get_settings()
    token = request.cookies.get(settings.session_cookie_name)
    if not token:
        raise UnauthorizedError("Not authenticated")

    token_hash = hashlib.sha256(token.encode()).hexdigest()
    session = await get_session_by_token_hash(db, token_hash)
    if session is None or session.revoked_at is not None:
        raise UnauthorizedError("Not authenticated")

    now = datetime.now(UTC)
    if now >= session.expires_at:
        raise UnauthorizedError("Session expired")
    if now - session.last_seen_at >= SESSION_IDLE_TIMEOUT:
        raise UnauthorizedError("Session expired")

    if now - session.last_seen_at >= LAST_SEEN_REFRESH_INTERVAL:
        session.last_seen_at = now
        await db.commit()

    return session


async def get_current_membership(
    session: Session = Depends(get_current_session),
    db: AsyncSession = Depends(get_db_session),
) -> Membership:
    """AUTH.md §7: a session whose membership is missing or INACTIVE is
    rejected at authentication time, not authorization time."""
    result = await db.execute(
        select(Membership).where(
            Membership.organization_id == session.organization_id,
            Membership.user_id == session.user_id,
            Membership.status == MembershipStatus.ACTIVE,
        )
    )
    membership = result.scalar_one_or_none()
    if membership is None:
        raise UnauthorizedError("Membership is no longer active")
    return membership

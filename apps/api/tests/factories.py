from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from trinol.core.ids import uuid7
from trinol.modules.identity.models import (
    AuthProvider,
    Invitation,
    Membership,
    MembershipRole,
    MembershipStatus,
    Organization,
    User,
)

# Plain factory functions, not factory_boy (TESTING.md §2): each adds+flushes
# a row and returns it, so a caller can chain them without repeating
# boilerplate.


async def make_organization(
    db: AsyncSession, *, name: str = "Test Org", slug: str | None = None
) -> Organization:
    org = Organization(id=uuid7(), name=name, slug=slug or f"test-org-{uuid7()}")
    db.add(org)
    await db.flush()
    return org


async def make_user(
    db: AsyncSession,
    *,
    email: str = "user@example.com",
    firebase_uid: str | None = None,
    auth_provider: AuthProvider = AuthProvider.PASSWORD,
    full_name: str = "Test User",
) -> User:
    user = User(
        id=uuid7(),
        firebase_uid=firebase_uid or f"fb-{uuid7()}",
        email=email,
        auth_provider=auth_provider,
        full_name=full_name,
    )
    db.add(user)
    await db.flush()
    return user


async def make_membership(
    db: AsyncSession,
    *,
    organization: Organization,
    user: User,
    role: MembershipRole = MembershipRole.MEMBER,
    status: MembershipStatus = MembershipStatus.ACTIVE,
) -> Membership:
    membership = Membership(
        id=uuid7(),
        organization_id=organization.id,
        user_id=user.id,
        role=role,
        status=status,
    )
    db.add(membership)
    await db.flush()
    return membership


async def make_invitation(
    db: AsyncSession,
    *,
    organization: Organization,
    email: str,
    invited_by: User,
    role: MembershipRole = MembershipRole.MEMBER,
    expires_in: timedelta = timedelta(days=7),
    token_hash: str | None = None,
) -> Invitation:
    invitation = Invitation(
        id=uuid7(),
        organization_id=organization.id,
        email=email,
        role=role,
        token_hash=token_hash or f"tok-{uuid7()}",
        invited_by=invited_by.id,
        expires_at=datetime.now(UTC) + expires_in,
    )
    db.add(invitation)
    await db.flush()
    return invitation

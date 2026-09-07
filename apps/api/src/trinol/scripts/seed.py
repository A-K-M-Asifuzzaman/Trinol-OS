"""`make seed` — Phase 1 plan decision 6.

One organization (the real company, `trinolit`) with three placeholder
users named after MASTER_PROMPT §36's role hints (Founder/Developer/
Designer) under the real `@trinolit.com` domain. These are structural
placeholders, not real accounts: no Firebase user exists for them yet, so
nobody can actually sign in as one until real accounts are created and their
`firebase_uid` is updated to match. Trivially edited later.

MASTER_PROMPT §36 also asks for clients, projects, tasks, leads, invoices,
and meetings — none of those tables exist yet (Phase 2+), so they're not
part of this script. Add them here when their phase lands.

Idempotent: re-running never duplicates a row, matched on the organization's
slug, each user's email, and the (organization, user) membership pair.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from trinol.core.authz.permissions import Role
from trinol.core.db.engine import get_session_factory
from trinol.core.db.org_session import register_org_scope_guard
from trinol.core.ids import uuid7
from trinol.modules.identity.models import (
    AuthProvider,
    Membership,
    MembershipStatus,
    Organization,
    User,
)

_ORG_SLUG = "trinolit"
_ORG_NAME = "TrinolIT"


@dataclass(frozen=True, slots=True)
class _SeedUser:
    full_name: str
    email: str
    role: Role


_SEED_USERS: tuple[_SeedUser, ...] = (
    _SeedUser(full_name="Founder", email="founder@trinolit.com", role=Role.OWNER),
    _SeedUser(full_name="Developer", email="developer@trinolit.com", role=Role.MEMBER),
    _SeedUser(full_name="Designer", email="designer@trinolit.com", role=Role.MEMBER),
)


async def _get_or_create_organization(db: AsyncSession) -> Organization:
    result = await db.execute(select(Organization).where(Organization.slug == _ORG_SLUG))
    organization = result.scalar_one_or_none()
    if organization is not None:
        return organization
    organization = Organization(id=uuid7(), name=_ORG_NAME, slug=_ORG_SLUG)
    db.add(organization)
    await db.flush()
    return organization


async def _get_or_create_user(db: AsyncSession, *, email: str, full_name: str) -> User:
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if user is not None:
        return user
    user = User(
        id=uuid7(),
        # Placeholder, not a real Firebase identity (see module docstring) —
        # distinguishable at a glance from a real "fb-..." uid.
        firebase_uid=f"seed-{email}",
        email=email,
        auth_provider=AuthProvider.PASSWORD,
        full_name=full_name,
    )
    db.add(user)
    await db.flush()
    return user


async def _ensure_membership(
    db: AsyncSession, *, organization: Organization, user: User, role: Role
) -> None:
    result = await db.execute(
        select(Membership).where(
            Membership.organization_id == organization.id, Membership.user_id == user.id
        )
    )
    if result.scalar_one_or_none() is not None:
        return
    db.add(
        Membership(
            id=uuid7(),
            organization_id=organization.id,
            user_id=user.id,
            role=role,
            status=MembershipStatus.ACTIVE,
        )
    )


async def seed() -> None:
    register_org_scope_guard()
    session_factory = get_session_factory()
    async with session_factory() as db:
        organization = await _get_or_create_organization(db)
        for entry in _SEED_USERS:
            user = await _get_or_create_user(db, email=entry.email, full_name=entry.full_name)
            await _ensure_membership(db, organization=organization, user=user, role=entry.role)
        await db.commit()


def main() -> None:
    asyncio.run(seed())


if __name__ == "__main__":
    main()

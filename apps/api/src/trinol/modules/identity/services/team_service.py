from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from trinol.core.db.org_session import OrgSession
from trinol.core.errors import ForbiddenError
from trinol.modules.identity.models import Membership, User
from trinol.modules.identity.services.membership_lookup import get_membership_in_org

# MASTER_PROMPT §17's Team page fields (name, email, avatar, role, job_title,
# status, joined_at) span two tables — Membership has no `user` relationship
# declared (models.py keeps plain FK columns, no ORM relationships anywhere
# in this codebase), so this assembles the two with a second query rather
# than an ORM join, same pattern invitation_service uses for its
# inviter/organization lookups.


@dataclass(frozen=True, slots=True)
class TeamMember:
    membership: Membership
    user: User


@dataclass(frozen=True, slots=True)
class TeamMemberList:
    items: list[TeamMember]
    total: int


def _ensure_actor_in_org(actor: Membership, organization_id: uuid.UUID) -> None:
    """Unlike invitation_service/membership_service, no role check: TEAM_READ
    is granted to every role (RBAC.md §2), so the route-level require() gate
    is the only authorization this needs — this is purely the same defense-
    in-depth org-match check every service here takes regardless."""
    if actor.organization_id != organization_id:
        raise ForbiddenError("Actor does not belong to this organization")


async def list_members(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    actor: Membership,
    limit: int = 50,
    offset: int = 0,
) -> TeamMemberList:
    _ensure_actor_in_org(actor, organization_id)

    total_result = await db.execute(
        select(func.count())
        .select_from(Membership)
        .where(Membership.organization_id == organization_id)
    )
    total = total_result.scalar_one()

    org_session = OrgSession(db, organization_id=organization_id)
    membership_result = await db.execute(
        org_session.select(Membership)
        # joined_at alone isn't a unique sort key (server_default now() can
        # tie within the same transaction, e.g. a seed script inserting
        # several memberships at once) — an OFFSET/LIMIT page over a
        # non-unique order can skip or repeat rows across pages. id (uuid7)
        # is unique and already time-ordered, so it breaks ties without
        # changing the intended chronological ordering.
        .order_by(Membership.joined_at.asc(), Membership.id.asc())
        .limit(limit)
        .offset(offset)
    )
    memberships = list(membership_result.scalars().all())

    users_by_id = await _users_by_id(db, [m.user_id for m in memberships])
    items = [TeamMember(membership=m, user=users_by_id[m.user_id]) for m in memberships]
    return TeamMemberList(items=items, total=total)


async def get_member(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    actor: Membership,
    membership_id: uuid.UUID,
) -> TeamMember:
    _ensure_actor_in_org(actor, organization_id)
    membership = await get_membership_in_org(
        db, organization_id=organization_id, membership_id=membership_id
    )
    users_by_id = await _users_by_id(db, [membership.user_id])
    return TeamMember(membership=membership, user=users_by_id[membership.user_id])


async def _users_by_id(db: AsyncSession, user_ids: list[uuid.UUID]) -> dict[uuid.UUID, User]:
    if not user_ids:
        return {}
    result = await db.execute(select(User).where(User.id.in_(user_ids)))
    return {user.id: user for user in result.scalars().all()}

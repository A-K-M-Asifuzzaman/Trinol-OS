from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from trinol.core.errors import NotFoundError
from trinol.modules.identity.models import Membership


async def get_membership_in_org(
    db: AsyncSession, *, organization_id: uuid.UUID, membership_id: uuid.UUID
) -> Membership:
    """Shared by membership_service (change_role/remove_member) and
    team_service (get_member) — an org+id scoped lookup that 404s on a
    cross-org id exactly like a genuinely missing one (RBAC.md §4: the query
    is already org-scoped, so there's no way to distinguish the two, and
    that's the point — never leak a 403 that would confirm the id exists in
    another org)."""
    result = await db.execute(
        select(Membership).where(
            Membership.organization_id == organization_id,
            Membership.id == membership_id,
        )
    )
    membership = result.scalar_one_or_none()
    if membership is None:
        raise NotFoundError("Membership not found")
    return membership

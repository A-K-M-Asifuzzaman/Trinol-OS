from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from trinol.modules.identity.models import Organization


async def lock_organization(db: AsyncSession, organization_id: uuid.UUID) -> None:
    """Takes a FOR UPDATE lock on the organization row so two concurrent
    mutations scoped to the same org serialize instead of racing a
    check-then-write. Shared by membership_service (guard 4 — last-owner
    protection) and invitation_service (duplicate-invitation creation) —
    factored out rather than duplicated so a fix to one lands in both.

    Whatever runs after this must roll back on exception, or the lock (and
    the transaction) stays open until something else closes the session —
    the same hazard that produced a genuine deadlock in Stage 7 once
    change_role/remove_member started writing activity events after taking
    this same lock.
    """
    stmt = select(Organization.id).where(Organization.id == organization_id).with_for_update()
    await db.execute(stmt)

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from trinol.core.db.org_session import OrgSession
from trinol.core.ids import uuid7
from trinol.platform.models import ActivityEvent


async def record(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    event: str,
    entity_type: str,
    entity_id: uuid.UUID,
    actor_id: uuid.UUID | None = None,
    metadata: dict[str, Any] | None = None,
    audit: bool = False,
    ip: str | None = None,
) -> ActivityEvent:
    """ADR-0006: one append-only table serving both the activity feed
    (audit=False) and the audit log (audit=True). Does *not* commit — the
    whole point (ADR-0006 Consequences) is that this writes inside the same
    transaction as the change it describes, so the log can never disagree
    with the data; the caller's own commit covers both.

    actor_id references users directly, not memberships (DATABASE.md §5.1's
    documented exception) — history must survive the actor leaving the org,
    and some events (a rejected login) have no membership to reference at
    all.
    """
    org_session = OrgSession(db, organization_id=organization_id)
    activity_event = ActivityEvent(
        id=uuid7(),
        organization_id=organization_id,
        actor_id=actor_id,
        event=event,
        entity_type=entity_type,
        entity_id=entity_id,
        event_metadata=metadata or {},
        is_audit=audit,
        ip=ip,
    )
    org_session.add(activity_event)
    await db.flush()
    return activity_event


async def list_feed(
    db: AsyncSession, *, organization_id: uuid.UUID, limit: int = 50, offset: int = 0
) -> list[ActivityEvent]:
    """§21's activity feed (is_audit=false). Enforcing ADR-0005's 200-item
    cap is the route's job (Stage 7 of Phase 2, `platform/routes/
    activity.py`), not this function's — it has no HTTP boundary of its
    own to defend."""
    org_session = OrgSession(db, organization_id=organization_id)
    stmt = (
        org_session.select(ActivityEvent)
        .where(ActivityEvent.is_audit.is_(False))
        .order_by(ActivityEvent.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def count_feed(db: AsyncSession, *, organization_id: uuid.UUID) -> int:
    """Separate from `list_feed` rather than folding into one dataclass
    return (like every `work` module list_* function) — this predates that
    convention (Phase 1 Stage 7) and `list_feed`/`list_audit`'s existing
    signature is already exercised by `test_activity_writer.py`; adding a
    function is less invasive than changing one both call sites depend on."""
    result = await db.execute(
        select(func.count())
        .select_from(ActivityEvent)
        .where(ActivityEvent.organization_id == organization_id, ActivityEvent.is_audit.is_(False))
    )
    return result.scalar_one()


async def list_audit(
    db: AsyncSession, *, organization_id: uuid.UUID, limit: int = 50, offset: int = 0
) -> list[ActivityEvent]:
    """§28's audit log (is_audit=true), ADMIN+ only at whatever future route
    wraps this (RBAC.md §2's AUDIT_READ permission)."""
    org_session = OrgSession(db, organization_id=organization_id)
    stmt = (
        org_session.select(ActivityEvent)
        .where(ActivityEvent.is_audit.is_(True))
        .order_by(ActivityEvent.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from trinol.core.db.org_session import OrgSession
from trinol.core.errors import ForbiddenError, NotFoundError
from trinol.core.ids import uuid7
from trinol.modules.identity.models import Membership
from trinol.modules.meetings.models import MeetingDecision
from trinol.modules.meetings.services.meeting_service import (
    can_write_meeting,
    ensure_actor_in_org,
    ensure_meeting_visible,
    get_meeting_in_org,
)
from trinol.platform.activity import record


@dataclass(frozen=True, slots=True)
class MeetingDecisionList:
    items: list[MeetingDecision]
    total: int


async def get_meeting_decision_in_org(
    db: AsyncSession, *, organization_id: uuid.UUID, meeting_id: uuid.UUID, decision_id: uuid.UUID
) -> MeetingDecision:
    result = await db.execute(
        select(MeetingDecision).where(
            MeetingDecision.organization_id == organization_id,
            MeetingDecision.meeting_id == meeting_id,
            MeetingDecision.id == decision_id,
        )
    )
    decision = result.scalar_one_or_none()
    if decision is None:
        raise NotFoundError("Meeting decision not found")
    return decision


async def list_decisions(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    actor: Membership,
    meeting_id: uuid.UUID,
    limit: int = 50,
    offset: int = 0,
) -> MeetingDecisionList:
    ensure_actor_in_org(actor, organization_id)
    meeting = await get_meeting_in_org(db, organization_id=organization_id, meeting_id=meeting_id)
    await ensure_meeting_visible(db, meeting=meeting, actor=actor)

    total_result = await db.execute(
        select(func.count())
        .select_from(MeetingDecision)
        .where(
            MeetingDecision.organization_id == organization_id,
            MeetingDecision.meeting_id == meeting_id,
        )
    )
    total = total_result.scalar_one()

    org_session = OrgSession(db, organization_id=organization_id)
    result = await db.execute(
        org_session.select(MeetingDecision)
        .where(MeetingDecision.meeting_id == meeting_id)
        .order_by(MeetingDecision.created_at.asc(), MeetingDecision.id.asc())
        .limit(limit)
        .offset(offset)
    )
    return MeetingDecisionList(items=list(result.scalars().all()), total=total)


async def create_decision(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    actor: Membership,
    meeting_id: uuid.UUID,
    body: str,
) -> MeetingDecision:
    """Decisions inherit the meeting's own edit rule (creator or
    MANAGER+), not an author-only rule — there's no author concept here
    to hang a separate rule on, same reasoning task_checklist_service's
    docstring already gives for its own sub-resource (ROADMAP.md Phase 4
    Stage 1 decision)."""
    ensure_actor_in_org(actor, organization_id)
    meeting = await get_meeting_in_org(db, organization_id=organization_id, meeting_id=meeting_id)
    if not can_write_meeting(actor, meeting):
        raise ForbiddenError("Insufficient permission to record a decision for this meeting")

    org_session = OrgSession(db, organization_id=organization_id)
    decision = MeetingDecision(
        id=uuid7(), meeting_id=meeting_id, body=body, decided_by=actor.user_id
    )
    org_session.add(decision)
    # Meaningful meeting content worth surfacing, same tier as
    # comment.created — unlike checklist items, which get no create-time
    # event at all (ROADMAP.md Stage 5 decision).
    await record(
        db,
        organization_id=organization_id,
        event="meeting_decision.created",
        entity_type="meeting_decision",
        entity_id=decision.id,
        actor_id=actor.user_id,
        metadata={"meeting_id": str(meeting_id)},
    )
    await db.commit()
    return decision


async def delete_decision(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    actor: Membership,
    meeting_id: uuid.UUID,
    decision_id: uuid.UUID,
) -> None:
    """ADR-0011: "Everything else is a hard delete, with the deletion
    recorded as an audit event" — a blanket rule, not limited to
    visibility-relevant deletes (same reasoning delete_checklist_item's
    docstring already gives for its own sub-resource)."""
    ensure_actor_in_org(actor, organization_id)
    meeting = await get_meeting_in_org(db, organization_id=organization_id, meeting_id=meeting_id)
    if not can_write_meeting(actor, meeting):
        raise ForbiddenError("Insufficient permission to delete this meeting's decisions")
    decision = await get_meeting_decision_in_org(
        db, organization_id=organization_id, meeting_id=meeting_id, decision_id=decision_id
    )

    decision_id_for_event = decision.id
    await record(
        db,
        organization_id=organization_id,
        event="meeting_decision.deleted",
        entity_type="meeting_decision",
        entity_id=decision_id_for_event,
        actor_id=actor.user_id,
        metadata={"meeting_id": str(meeting_id)},
        audit=True,
    )
    await db.delete(decision)
    await db.commit()

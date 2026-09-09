from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from trinol.core.db.org_session import OrgSession
from trinol.core.errors import ConflictError, ForbiddenError, NotFoundError
from trinol.core.ids import uuid7
from trinol.modules.identity.models import Membership
from trinol.modules.meetings.models import MeetingParticipant, MeetingParticipantResponse
from trinol.modules.meetings.services.meeting_service import (
    can_write_meeting,
    ensure_actor_in_org,
    ensure_meeting_visible,
    get_meeting_in_org,
)
from trinol.modules.work.services.project_service import get_active_membership_by_user
from trinol.platform.activity import record


@dataclass(frozen=True, slots=True)
class MeetingParticipantList:
    items: list[MeetingParticipant]
    total: int


async def get_meeting_participant_in_org(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    meeting_id: uuid.UUID,
    participant_id: uuid.UUID,
) -> MeetingParticipant:
    result = await db.execute(
        select(MeetingParticipant).where(
            MeetingParticipant.organization_id == organization_id,
            MeetingParticipant.meeting_id == meeting_id,
            MeetingParticipant.id == participant_id,
        )
    )
    participant = result.scalar_one_or_none()
    if participant is None:
        raise NotFoundError("Meeting participant not found")
    return participant


async def list_meeting_participants(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    actor: Membership,
    meeting_id: uuid.UUID,
    limit: int = 50,
    offset: int = 0,
) -> MeetingParticipantList:
    ensure_actor_in_org(actor, organization_id)
    meeting = await get_meeting_in_org(db, organization_id=organization_id, meeting_id=meeting_id)
    await ensure_meeting_visible(db, meeting=meeting, actor=actor)

    total_result = await db.execute(
        select(func.count())
        .select_from(MeetingParticipant)
        .where(
            MeetingParticipant.organization_id == organization_id,
            MeetingParticipant.meeting_id == meeting_id,
        )
    )
    total = total_result.scalar_one()

    org_session = OrgSession(db, organization_id=organization_id)
    result = await db.execute(
        org_session.select(MeetingParticipant)
        .where(MeetingParticipant.meeting_id == meeting_id)
        .order_by(MeetingParticipant.id.asc())
        .limit(limit)
        .offset(offset)
    )
    return MeetingParticipantList(items=list(result.scalars().all()), total=total)


async def add_participant(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    actor: Membership,
    meeting_id: uuid.UUID,
    user_id: uuid.UUID | None,
    external_email: str | None,
) -> MeetingParticipant:
    """RBAC.md §3 'Meeting edit' rule applies to roster management too —
    same reasoning project_member_service.add_project_member already uses
    for its own can_manage_members gate (creator/MANAGER+ implies
    visibility, no separate check needed)."""
    ensure_actor_in_org(actor, organization_id)
    meeting = await get_meeting_in_org(db, organization_id=organization_id, meeting_id=meeting_id)
    if not can_write_meeting(actor, meeting):
        raise ForbiddenError("Insufficient permission to manage this meeting's participants")

    if user_id is not None:
        await get_active_membership_by_user(db, organization_id=organization_id, user_id=user_id)
        existing = await db.execute(
            select(MeetingParticipant.id).where(
                MeetingParticipant.organization_id == organization_id,
                MeetingParticipant.meeting_id == meeting_id,
                MeetingParticipant.user_id == user_id,
            )
        )
    else:
        existing = await db.execute(
            select(MeetingParticipant.id).where(
                MeetingParticipant.organization_id == organization_id,
                MeetingParticipant.meeting_id == meeting_id,
                MeetingParticipant.external_email == external_email,
            )
        )
    if existing.scalar_one_or_none() is not None:
        raise ConflictError("This person is already a participant of this meeting")

    org_session = OrgSession(db, organization_id=organization_id)
    participant = MeetingParticipant(
        id=uuid7(),
        meeting_id=meeting_id,
        user_id=user_id,
        external_email=external_email,
        response=MeetingParticipantResponse.PENDING,
    )
    org_session.add(participant)
    try:
        # RBAC.md §3: adding a participant changes who can see the meeting
        # (ensure_meeting_visible's rule depends on this table) — always
        # is_audit=true, never ordinary feed content, same reasoning
        # project_member.added already established.
        await record(
            db,
            organization_id=organization_id,
            event="meeting_participant.added",
            entity_type="meeting_participant",
            entity_id=participant.id,
            actor_id=actor.user_id,
            metadata={"meeting_id": str(meeting_id)},
            audit=True,
        )
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise ConflictError("This person is already a participant of this meeting") from None
    return participant


async def remove_participant(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    actor: Membership,
    meeting_id: uuid.UUID,
    participant_id: uuid.UUID,
) -> None:
    ensure_actor_in_org(actor, organization_id)
    meeting = await get_meeting_in_org(db, organization_id=organization_id, meeting_id=meeting_id)
    if not can_write_meeting(actor, meeting):
        raise ForbiddenError("Insufficient permission to manage this meeting's participants")

    participant = await get_meeting_participant_in_org(
        db, organization_id=organization_id, meeting_id=meeting_id, participant_id=participant_id
    )
    participant_id_for_event = participant.id
    # Same guard-6 reasoning as add_participant above: always is_audit=true.
    await record(
        db,
        organization_id=organization_id,
        event="meeting_participant.removed",
        entity_type="meeting_participant",
        entity_id=participant_id_for_event,
        actor_id=actor.user_id,
        metadata={"meeting_id": str(meeting_id)},
        audit=True,
    )
    await db.delete(participant)
    await db.commit()


async def update_participant_response(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    actor: Membership,
    meeting_id: uuid.UUID,
    participant_id: uuid.UUID,
    response: MeetingParticipantResponse,
) -> MeetingParticipant:
    """Phase 4 Stage 1 decision: a participant may update their own RSVP
    regardless of can_write_meeting — a narrow exception, not a broader
    edit right. No activity event: unlike add/remove, this doesn't change
    who can see the meeting, so it isn't guard 6's is_audit=true case, and
    it isn't ordinary feed content either (no other module records a
    person updating their own status field as a discrete event)."""
    ensure_actor_in_org(actor, organization_id)
    meeting = await get_meeting_in_org(db, organization_id=organization_id, meeting_id=meeting_id)
    participant = await get_meeting_participant_in_org(
        db, organization_id=organization_id, meeting_id=meeting_id, participant_id=participant_id
    )
    is_self = participant.user_id == actor.user_id
    if not is_self and not can_write_meeting(actor, meeting):
        raise ForbiddenError("Insufficient permission to update this participant's response")

    participant.response = response
    await db.commit()
    return participant

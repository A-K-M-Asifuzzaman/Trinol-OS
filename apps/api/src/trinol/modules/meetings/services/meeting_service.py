from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from trinol.core.authz.permissions import Role
from trinol.core.db.org_session import OrgSession
from trinol.core.errors import ForbiddenError, NotFoundError, UnprocessableEntityError
from trinol.core.ids import uuid7
from trinol.modules.crm.services.client_service import get_client_in_org
from trinol.modules.identity.models import Membership
from trinol.modules.meetings.models import Meeting, MeetingParticipant
from trinol.modules.work.services.project_service import get_project_in_org
from trinol.platform.activity import record

_MANAGER_UP = (Role.MANAGER, Role.ADMIN, Role.OWNER)


@dataclass(frozen=True, slots=True)
class MeetingList:
    items: list[Meeting]
    total: int


def ensure_actor_in_org(actor: Membership, organization_id: uuid.UUID) -> None:
    """Defense in depth, same reasoning as every other module's own copy of
    this check (e.g. work.services.project_service.ensure_actor_in_org)."""
    if actor.organization_id != organization_id:
        raise ForbiddenError("Actor does not belong to this organization")


async def get_meeting_in_org(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    meeting_id: uuid.UUID,
    for_update: bool = False,
) -> Meeting:
    """Org-scoped lookup — 404s a cross-org id exactly like a missing one
    (RBAC.md §4), same pattern as get_project_in_org/get_client_in_org.
    `for_update`: takes a row lock so a caller's own check-then-write
    against this meeting's children (meeting_participant_service.
    add_participant's duplicate check) serializes against a concurrent one
    instead of racing — same reason and shape as lead_service.
    get_lead_in_org's own `for_update` param."""
    stmt = (
        select(Meeting)
        .where(Meeting.organization_id == organization_id, Meeting.id == meeting_id)
        .execution_options(populate_existing=True)
    )
    if for_update:
        stmt = stmt.with_for_update()
    result = await db.execute(stmt)
    meeting = result.scalar_one_or_none()
    if meeting is None:
        raise NotFoundError("Meeting not found")
    return meeting


async def is_meeting_participant(
    db: AsyncSession, *, organization_id: uuid.UUID, meeting_id: uuid.UUID, user_id: uuid.UUID
) -> bool:
    result = await db.execute(
        select(MeetingParticipant.id).where(
            MeetingParticipant.organization_id == organization_id,
            MeetingParticipant.meeting_id == meeting_id,
            MeetingParticipant.user_id == user_id,
        )
    )
    return result.scalar_one_or_none() is not None


async def ensure_meeting_visible(db: AsyncSession, *, meeting: Meeting, actor: Membership) -> None:
    """RBAC.md §3 'Meeting visibility' rule (Phase 4 Stage 1 gap-fill):
    MANAGER+, the meeting's own creator, or a meeting_participants row for
    the actor — mirrors ensure_project_visible's shape exactly, since a
    meeting is equally a multi-person resource."""
    if actor.role in _MANAGER_UP:
        return
    if meeting.created_by == actor.user_id:
        return
    if await is_meeting_participant(
        db, organization_id=actor.organization_id, meeting_id=meeting.id, user_id=actor.user_id
    ):
        return
    raise ForbiddenError("Not a participant of this meeting")


def can_write_meeting(actor: Membership, meeting: Meeting) -> bool:
    """RBAC.md §3 'Meeting edit': creator or MANAGER+. A participant does
    not gain edit rights merely by being invited (Phase 4 Stage 1
    decision)."""
    return actor.role in _MANAGER_UP or meeting.created_by == actor.user_id


async def _validate_client_and_project(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    client_id: uuid.UUID | None,
    project_id: uuid.UUID | None,
) -> None:
    if client_id is not None:
        await get_client_in_org(db, organization_id=organization_id, client_id=client_id)
    if project_id is not None:
        await get_project_in_org(db, organization_id=organization_id, project_id=project_id)


async def create_meeting(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    actor: Membership,
    title: str,
    description: str | None,
    starts_at: Any,
    ends_at: Any,
    client_id: uuid.UUID | None,
    project_id: uuid.UUID | None,
    meeting_url: str | None,
    location: str | None,
    notes: str | None,
) -> Meeting:
    ensure_actor_in_org(actor, organization_id)
    # RBAC.md §2: "Meetings: create/edit own" is granted to every role — no
    # ownership check on create, there's no prior resource to own yet.
    await _validate_client_and_project(
        db, organization_id=organization_id, client_id=client_id, project_id=project_id
    )

    org_session = OrgSession(db, organization_id=organization_id)
    meeting = Meeting(
        id=uuid7(),
        title=title,
        description=description,
        starts_at=starts_at,
        ends_at=ends_at,
        client_id=client_id,
        project_id=project_id,
        meeting_url=meeting_url,
        location=location,
        notes=notes,
        created_by=actor.user_id,
    )
    org_session.add(meeting)
    # ROADMAP.md Phase 2 decision 2 / Phase 4 Stage 2 decision: ordinary
    # feed content, is_audit=false, wired inline rather than deferred to a
    # later stage (Phase 2's pattern, not Phase 3's retrofit).
    await record(
        db,
        organization_id=organization_id,
        event="meeting.created",
        entity_type="meeting",
        entity_id=meeting.id,
        actor_id=actor.user_id,
        metadata={"title": meeting.title},
    )
    await db.commit()
    return meeting


async def list_meetings(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    actor: Membership,
    limit: int = 50,
    offset: int = 0,
) -> MeetingList:
    ensure_actor_in_org(actor, organization_id)

    base_filters: list[Any] = []
    if actor.role not in _MANAGER_UP:
        # ensure_meeting_visible's rule, applied uniformly to the list too —
        # otherwise a MEMBER could read meeting fields off the list
        # response for a meeting they can't open (same reasoning
        # list_projects already applies for project_members).
        participant_rows = await db.execute(
            select(MeetingParticipant.meeting_id).where(
                MeetingParticipant.organization_id == organization_id,
                MeetingParticipant.user_id == actor.user_id,
            )
        )
        visible_ids = {row[0] for row in participant_rows.all()}
        base_filters.append((Meeting.created_by == actor.user_id) | (Meeting.id.in_(visible_ids)))

    total_result = await db.execute(
        select(func.count())
        .select_from(Meeting)
        .where(Meeting.organization_id == organization_id, *base_filters)
    )
    total = total_result.scalar_one()

    org_session = OrgSession(db, organization_id=organization_id)
    result = await db.execute(
        org_session.select(Meeting)
        .where(*base_filters)
        .order_by(Meeting.starts_at.asc(), Meeting.id.asc())
        .limit(limit)
        .offset(offset)
    )
    return MeetingList(items=list(result.scalars().all()), total=total)


async def get_meeting(
    db: AsyncSession, *, organization_id: uuid.UUID, actor: Membership, meeting_id: uuid.UUID
) -> Meeting:
    ensure_actor_in_org(actor, organization_id)
    meeting = await get_meeting_in_org(db, organization_id=organization_id, meeting_id=meeting_id)
    await ensure_meeting_visible(db, meeting=meeting, actor=actor)
    return meeting


async def update_meeting(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    actor: Membership,
    meeting_id: uuid.UUID,
    updates: dict[str, Any],
) -> Meeting:
    ensure_actor_in_org(actor, organization_id)
    meeting = await get_meeting_in_org(db, organization_id=organization_id, meeting_id=meeting_id)
    if not can_write_meeting(actor, meeting):
        raise ForbiddenError("Insufficient permission to edit this meeting")

    resulting_starts = updates.get("starts_at", meeting.starts_at)
    resulting_ends = updates.get("ends_at", meeting.ends_at)
    if resulting_ends <= resulting_starts:
        raise UnprocessableEntityError("ends_at must be after starts_at")

    await _validate_client_and_project(
        db,
        organization_id=organization_id,
        client_id=updates.get("client_id", meeting.client_id),
        project_id=updates.get("project_id", meeting.project_id),
    )

    for field, value in updates.items():
        setattr(meeting, field, value)

    await db.commit()
    return await get_meeting_in_org(db, organization_id=organization_id, meeting_id=meeting_id)


async def delete_meeting(
    db: AsyncSession, *, organization_id: uuid.UUID, actor: Membership, meeting_id: uuid.UUID
) -> None:
    """ADR-0011: meetings are hard-deleted (not among the four soft-deleted
    entities), cascading to participants/decisions/actions (Stage 1's
    CASCADE FKs). The audit event is the only remaining record once the
    row is gone, so it's written in the same transaction (mirrors
    task_service.delete_task exactly)."""
    ensure_actor_in_org(actor, organization_id)
    meeting = await get_meeting_in_org(db, organization_id=organization_id, meeting_id=meeting_id)
    if not can_write_meeting(actor, meeting):
        raise ForbiddenError("Insufficient permission to delete this meeting")

    await record(
        db,
        organization_id=organization_id,
        event="meeting.deleted",
        entity_type="meeting",
        entity_id=meeting.id,
        actor_id=actor.user_id,
        metadata={"title": meeting.title},
        audit=True,
    )
    await db.delete(meeting)
    await db.commit()

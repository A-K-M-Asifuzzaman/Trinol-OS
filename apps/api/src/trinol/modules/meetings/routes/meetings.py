from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from trinol.core.authz.permissions import Permission
from trinol.core.authz.require import require
from trinol.core.db.engine import get_db_session
from trinol.modules.identity.deps import get_current_membership
from trinol.modules.identity.models import Membership
from trinol.modules.meetings.models import Meeting, MeetingParticipant
from trinol.modules.meetings.schemas import (
    MeetingCreateRequest,
    MeetingListResponse,
    MeetingParticipantAddRequest,
    MeetingParticipantListResponse,
    MeetingParticipantResponse,
    MeetingParticipantResponseUpdateRequest,
    MeetingResponse,
    MeetingUpdateRequest,
)
from trinol.modules.meetings.services.meeting_participant_service import (
    add_participant,
    list_meeting_participants,
    remove_participant,
    update_participant_response,
)
from trinol.modules.meetings.services.meeting_service import (
    create_meeting,
    delete_meeting,
    get_meeting,
    list_meetings,
    update_meeting,
)

router = APIRouter(prefix="/api/v1/meetings", tags=["meetings"])


def meeting_to_response(meeting: Meeting) -> MeetingResponse:
    return MeetingResponse(
        id=meeting.id,
        title=meeting.title,
        description=meeting.description,
        starts_at=meeting.starts_at,
        ends_at=meeting.ends_at,
        client_id=meeting.client_id,
        project_id=meeting.project_id,
        meeting_url=meeting.meeting_url,
        location=meeting.location,
        notes=meeting.notes,
        external_event_id=meeting.external_event_id,
        created_by=meeting.created_by,
        created_at=meeting.created_at,
        updated_at=meeting.updated_at,
    )


@router.post(
    "",
    response_model=MeetingResponse,
    status_code=201,
    dependencies=[Depends(require(Permission.MEETING_WRITE_OWN))],
)
async def create_meeting_route(
    payload: MeetingCreateRequest,
    membership: Membership = Depends(get_current_membership),
    db: AsyncSession = Depends(get_db_session),
) -> MeetingResponse:
    meeting = await create_meeting(
        db,
        organization_id=membership.organization_id,
        actor=membership,
        title=payload.title,
        description=payload.description,
        starts_at=payload.starts_at,
        ends_at=payload.ends_at,
        client_id=payload.client_id,
        project_id=payload.project_id,
        meeting_url=payload.meeting_url,
        location=payload.location,
        notes=payload.notes,
    )
    return meeting_to_response(meeting)


@router.get(
    "", response_model=MeetingListResponse, dependencies=[Depends(require(Permission.MEETING_READ))]
)
async def list_meetings_route(
    limit: int = Query(default=50, ge=1, le=200),  # ADR-0005: default 50, hard cap 200
    offset: int = Query(default=0, ge=0),
    membership: Membership = Depends(get_current_membership),
    db: AsyncSession = Depends(get_db_session),
) -> MeetingListResponse:
    result = await list_meetings(
        db, organization_id=membership.organization_id, actor=membership, limit=limit, offset=offset
    )
    return MeetingListResponse(
        items=[meeting_to_response(m) for m in result.items], total=result.total
    )


@router.get(
    "/{meeting_id}",
    response_model=MeetingResponse,
    dependencies=[Depends(require(Permission.MEETING_READ))],
)
async def get_meeting_route(
    meeting_id: uuid.UUID,
    membership: Membership = Depends(get_current_membership),
    db: AsyncSession = Depends(get_db_session),
) -> MeetingResponse:
    meeting = await get_meeting(
        db, organization_id=membership.organization_id, actor=membership, meeting_id=meeting_id
    )
    return meeting_to_response(meeting)


@router.patch(
    "/{meeting_id}",
    response_model=MeetingResponse,
    dependencies=[Depends(require(Permission.MEETING_WRITE_OWN))],
)
async def update_meeting_route(
    meeting_id: uuid.UUID,
    payload: MeetingUpdateRequest,
    membership: Membership = Depends(get_current_membership),
    db: AsyncSession = Depends(get_db_session),
) -> MeetingResponse:
    updates = payload.model_dump(exclude_unset=True)
    meeting = await update_meeting(
        db,
        organization_id=membership.organization_id,
        actor=membership,
        meeting_id=meeting_id,
        updates=updates,
    )
    return meeting_to_response(meeting)


@router.delete(
    "/{meeting_id}",
    status_code=204,
    dependencies=[Depends(require(Permission.MEETING_WRITE_OWN))],
)
async def delete_meeting_route(
    meeting_id: uuid.UUID,
    membership: Membership = Depends(get_current_membership),
    db: AsyncSession = Depends(get_db_session),
) -> None:
    await delete_meeting(
        db, organization_id=membership.organization_id, actor=membership, meeting_id=meeting_id
    )


def _participant_to_response(participant: MeetingParticipant) -> MeetingParticipantResponse:
    return MeetingParticipantResponse(
        id=participant.id,
        meeting_id=participant.meeting_id,
        user_id=participant.user_id,
        external_email=participant.external_email,
        response=participant.response,
    )


@router.post(
    "/{meeting_id}/participants",
    response_model=MeetingParticipantResponse,
    status_code=201,
    dependencies=[Depends(require(Permission.MEETING_WRITE_OWN))],
)
async def add_participant_route(
    meeting_id: uuid.UUID,
    payload: MeetingParticipantAddRequest,
    membership: Membership = Depends(get_current_membership),
    db: AsyncSession = Depends(get_db_session),
) -> MeetingParticipantResponse:
    participant = await add_participant(
        db,
        organization_id=membership.organization_id,
        actor=membership,
        meeting_id=meeting_id,
        user_id=payload.user_id,
        external_email=payload.external_email,
    )
    return _participant_to_response(participant)


@router.get(
    "/{meeting_id}/participants",
    response_model=MeetingParticipantListResponse,
    dependencies=[Depends(require(Permission.MEETING_READ))],
)
async def list_meeting_participants_route(
    meeting_id: uuid.UUID,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    membership: Membership = Depends(get_current_membership),
    db: AsyncSession = Depends(get_db_session),
) -> MeetingParticipantListResponse:
    result = await list_meeting_participants(
        db,
        organization_id=membership.organization_id,
        actor=membership,
        meeting_id=meeting_id,
        limit=limit,
        offset=offset,
    )
    return MeetingParticipantListResponse(
        items=[_participant_to_response(p) for p in result.items], total=result.total
    )


@router.patch(
    "/{meeting_id}/participants/{participant_id}",
    response_model=MeetingParticipantResponse,
    dependencies=[Depends(require(Permission.MEETING_WRITE_OWN))],
)
async def update_participant_response_route(
    meeting_id: uuid.UUID,
    participant_id: uuid.UUID,
    payload: MeetingParticipantResponseUpdateRequest,
    membership: Membership = Depends(get_current_membership),
    db: AsyncSession = Depends(get_db_session),
) -> MeetingParticipantResponse:
    participant = await update_participant_response(
        db,
        organization_id=membership.organization_id,
        actor=membership,
        meeting_id=meeting_id,
        participant_id=participant_id,
        response=payload.response,
    )
    return _participant_to_response(participant)


@router.delete(
    "/{meeting_id}/participants/{participant_id}",
    status_code=204,
    dependencies=[Depends(require(Permission.MEETING_WRITE_OWN))],
)
async def remove_participant_route(
    meeting_id: uuid.UUID,
    participant_id: uuid.UUID,
    membership: Membership = Depends(get_current_membership),
    db: AsyncSession = Depends(get_db_session),
) -> None:
    await remove_participant(
        db,
        organization_id=membership.organization_id,
        actor=membership,
        meeting_id=meeting_id,
        participant_id=participant_id,
    )

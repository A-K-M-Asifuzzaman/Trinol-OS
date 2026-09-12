from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from trinol.core.authz.permissions import Permission
from trinol.core.authz.require import require
from trinol.core.db.engine import get_db_session
from trinol.modules.ai.schemas import MeetingSummaryResponse
from trinol.modules.ai.services.client import AIClient
from trinol.modules.ai.services.deps import get_ai_client
from trinol.modules.ai.services.meeting_summary_service import (
    get_meeting_summary,
    summarize_meeting,
)
from trinol.modules.identity.deps import get_current_membership
from trinol.modules.identity.models import Membership

router = APIRouter(prefix="/api/v1/meetings", tags=["ai"])


def _to_response(summary: object) -> MeetingSummaryResponse:
    return MeetingSummaryResponse.model_validate(summary, from_attributes=True)


@router.post(
    "/{meeting_id}/summary",
    response_model=MeetingSummaryResponse,
    dependencies=[Depends(require(Permission.MEETING_WRITE_OWN))],
)
async def summarize_meeting_route(
    meeting_id: uuid.UUID,
    membership: Membership = Depends(get_current_membership),
    db: AsyncSession = Depends(get_db_session),
    ai_client: AIClient = Depends(get_ai_client),
) -> MeetingSummaryResponse:
    summary = await summarize_meeting(
        db,
        organization_id=membership.organization_id,
        actor=membership,
        meeting_id=meeting_id,
        ai_client=ai_client,
    )
    return _to_response(summary)


@router.get(
    "/{meeting_id}/summary",
    response_model=MeetingSummaryResponse,
    dependencies=[Depends(require(Permission.MEETING_READ))],
)
async def get_meeting_summary_route(
    meeting_id: uuid.UUID,
    membership: Membership = Depends(get_current_membership),
    db: AsyncSession = Depends(get_db_session),
) -> MeetingSummaryResponse:
    summary = await get_meeting_summary(
        db, organization_id=membership.organization_id, actor=membership, meeting_id=meeting_id
    )
    return _to_response(summary)

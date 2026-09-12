from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from trinol.core.authz.permissions import Permission
from trinol.core.authz.require import require
from trinol.core.db.engine import get_db_session
from trinol.modules.ai.services.action_extraction_service import extract_actions
from trinol.modules.ai.services.client import AIClient
from trinol.modules.ai.services.deps import get_ai_client
from trinol.modules.identity.deps import get_current_membership
from trinol.modules.identity.models import Membership
from trinol.modules.meetings.models import MeetingAction
from trinol.modules.meetings.schemas import MeetingActionListResponse, MeetingActionResponse

router = APIRouter(prefix="/api/v1/meetings", tags=["ai"])


def _to_response(action: MeetingAction) -> MeetingActionResponse:
    return MeetingActionResponse(
        id=action.id,
        meeting_id=action.meeting_id,
        description=action.description,
        owner_id=action.owner_id,
        due_date=action.due_date,
        task_id=action.task_id,
        source=action.source,
        created_at=action.created_at,
    )


@router.post(
    "/{meeting_id}/actions/extract",
    response_model=MeetingActionListResponse,
    status_code=201,
    dependencies=[Depends(require(Permission.MEETING_WRITE_OWN))],
)
async def extract_meeting_actions_route(
    meeting_id: uuid.UUID,
    membership: Membership = Depends(get_current_membership),
    db: AsyncSession = Depends(get_db_session),
    ai_client: AIClient = Depends(get_ai_client),
) -> MeetingActionListResponse:
    actions = await extract_actions(
        db,
        organization_id=membership.organization_id,
        actor=membership,
        meeting_id=meeting_id,
        ai_client=ai_client,
    )
    items = [_to_response(a) for a in actions]
    return MeetingActionListResponse(items=items, total=len(items))

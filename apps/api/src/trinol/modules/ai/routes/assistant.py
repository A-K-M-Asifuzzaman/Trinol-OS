from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from trinol.core.authz.permissions import Permission
from trinol.core.authz.require import require
from trinol.core.db.engine import get_db_session
from trinol.modules.ai.schemas import AssistantAskRequest, AssistantAskResponse
from trinol.modules.ai.services.assistant_service import ask
from trinol.modules.ai.services.client import AIClient
from trinol.modules.ai.services.deps import get_ai_client
from trinol.modules.identity.deps import get_current_membership
from trinol.modules.identity.models import Membership

router = APIRouter(prefix="/api/v1/ai", tags=["ai"])


@router.post(
    "/assistant/ask",
    response_model=AssistantAskResponse,
    dependencies=[Depends(require(Permission.AI_ASSISTANT_USE))],
)
async def ask_assistant_route(
    payload: AssistantAskRequest,
    membership: Membership = Depends(get_current_membership),
    db: AsyncSession = Depends(get_db_session),
    ai_client: AIClient = Depends(get_ai_client),
) -> AssistantAskResponse:
    answer = await ask(
        db,
        organization_id=membership.organization_id,
        actor=membership,
        question=payload.question,
        ai_client=ai_client,
    )
    return AssistantAskResponse(answer=answer.text, source_count=answer.source_count)

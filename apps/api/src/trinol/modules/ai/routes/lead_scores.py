from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from trinol.core.authz.permissions import Permission
from trinol.core.authz.require import require
from trinol.core.db.engine import get_db_session
from trinol.modules.ai.models import LeadScore
from trinol.modules.ai.schemas import LeadScoreResponse
from trinol.modules.ai.services.client import AIClient
from trinol.modules.ai.services.deps import get_ai_client
from trinol.modules.ai.services.lead_scoring_service import get_lead_score, score_lead
from trinol.modules.identity.deps import get_current_membership
from trinol.modules.identity.models import Membership

router = APIRouter(prefix="/api/v1/leads", tags=["ai"])


def _to_response(score: LeadScore, *, stale: bool) -> LeadScoreResponse:
    return LeadScoreResponse(
        id=score.id,
        lead_id=score.lead_id,
        score=score.score,
        rationale=score.rationale,
        computed_at=score.computed_at,
        computed_by=score.computed_by,
        stale=stale,
    )


@router.post(
    "/{lead_id}/score",
    response_model=LeadScoreResponse,
    dependencies=[Depends(require(Permission.LEAD_WRITE))],
)
async def score_lead_route(
    lead_id: uuid.UUID,
    membership: Membership = Depends(get_current_membership),
    db: AsyncSession = Depends(get_db_session),
    ai_client: AIClient = Depends(get_ai_client),
) -> LeadScoreResponse:
    score = await score_lead(
        db,
        organization_id=membership.organization_id,
        actor=membership,
        lead_id=lead_id,
        ai_client=ai_client,
    )
    # Just (re)computed against the lead's current state — trivially not
    # stale yet.
    return _to_response(score, stale=False)


@router.get(
    "/{lead_id}/score",
    response_model=LeadScoreResponse,
    dependencies=[Depends(require(Permission.LEAD_READ))],
)
async def get_lead_score_route(
    lead_id: uuid.UUID,
    membership: Membership = Depends(get_current_membership),
    db: AsyncSession = Depends(get_db_session),
) -> LeadScoreResponse:
    score, stale = await get_lead_score(
        db, organization_id=membership.organization_id, actor=membership, lead_id=lead_id
    )
    return _to_response(score, stale=stale)

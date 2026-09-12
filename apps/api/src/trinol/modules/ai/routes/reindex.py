from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from trinol.core.authz.permissions import Permission
from trinol.core.authz.require import require
from trinol.core.db.engine import get_db_session
from trinol.modules.ai.schemas import ReindexResponse
from trinol.modules.ai.services.client import AIClient
from trinol.modules.ai.services.deps import get_ai_client
from trinol.modules.ai.services.embedding_service import reindex_stale
from trinol.modules.identity.deps import get_current_membership
from trinol.modules.identity.models import Membership

router = APIRouter(prefix="/api/v1/ai", tags=["ai"])

# ADMIN+ (reusing Permission.ORG_SETTINGS_WRITE's tier, not a new
# permission — Phase 8 Stage 3 plan): a full reindex is an operational,
# cost-incurring action for recovery/backfill, not routine use.
# reindex_stale() already runs automatically (bounded) inside retrieval
# (Stage 4), so this route exists only for manual recovery.


@router.post(
    "/reindex",
    response_model=ReindexResponse,
    dependencies=[Depends(require(Permission.ORG_SETTINGS_WRITE))],
)
async def reindex_route(
    membership: Membership = Depends(get_current_membership),
    db: AsyncSession = Depends(get_db_session),
    ai_client: AIClient = Depends(get_ai_client),
) -> ReindexResponse:
    count = await reindex_stale(
        db,
        organization_id=membership.organization_id,
        actor=membership,
        ai_client=ai_client,
    )
    return ReindexResponse(reindexed=count)

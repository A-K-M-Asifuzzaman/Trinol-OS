from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from trinol.core.authz.permissions import Permission
from trinol.core.authz.require import require
from trinol.core.db.engine import get_db_session
from trinol.modules.ai.schemas import SearchResponse, SearchResultItem
from trinol.modules.ai.services.client import AIClient
from trinol.modules.ai.services.deps import get_ai_client
from trinol.modules.ai.services.retrieval_service import search_knowledge
from trinol.modules.identity.deps import get_current_membership
from trinol.modules.identity.models import Membership

router = APIRouter(prefix="/api/v1/ai", tags=["ai"])


@router.get(
    "/search",
    response_model=SearchResponse,
    dependencies=[Depends(require(Permission.AI_ASSISTANT_USE))],
)
async def search_route(
    q: str = Query(min_length=1, max_length=500),
    membership: Membership = Depends(get_current_membership),
    db: AsyncSession = Depends(get_db_session),
    ai_client: AIClient = Depends(get_ai_client),
) -> SearchResponse:
    chunks = await search_knowledge(
        db,
        organization_id=membership.organization_id,
        actor=membership,
        query=q,
        ai_client=ai_client,
    )
    return SearchResponse(
        items=[
            SearchResultItem(
                source_type=chunk.source_type, source_id=chunk.source_id, content=chunk.content
            )
            for chunk in chunks
        ]
    )

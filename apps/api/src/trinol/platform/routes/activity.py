from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from trinol.core.authz.permissions import Permission
from trinol.core.authz.require import require
from trinol.core.db.engine import get_db_session
from trinol.modules.identity.deps import get_current_membership
from trinol.modules.identity.models import Membership
from trinol.platform.activity import count_feed, list_feed
from trinol.platform.models import ActivityEvent
from trinol.platform.schemas import ActivityEventResponse, ActivityFeedResponse

router = APIRouter(prefix="/api/v1/activity", tags=["platform"])


def _event_to_response(event: ActivityEvent) -> ActivityEventResponse:
    return ActivityEventResponse(
        id=event.id,
        event=event.event,
        entity_type=event.entity_type,
        entity_id=event.entity_id,
        actor_id=event.actor_id,
        metadata=event.event_metadata,
        created_at=event.created_at,
    )


@router.get(
    "",
    response_model=ActivityFeedResponse,
    # MASTER_PROMPT §21's "Recent activity" dashboard widget is org-wide,
    # not project-scoped (list_feed has no project filter) — PROJECT_READ
    # is the closest existing MEMBER-tier permission to "work visibility"
    # (ROADMAP.md Phase 2 Stage 7 decision), not a new one invented for
    # this one route.
    dependencies=[Depends(require(Permission.PROJECT_READ))],
)
async def list_activity_feed_route(
    limit: int = Query(default=50, ge=1, le=200),  # ADR-0005: default 50, hard cap 200
    offset: int = Query(default=0, ge=0),
    membership: Membership = Depends(get_current_membership),
    db: AsyncSession = Depends(get_db_session),
) -> ActivityFeedResponse:
    events = await list_feed(
        db, organization_id=membership.organization_id, limit=limit, offset=offset
    )
    total = await count_feed(db, organization_id=membership.organization_id)
    return ActivityFeedResponse(items=[_event_to_response(e) for e in events], total=total)

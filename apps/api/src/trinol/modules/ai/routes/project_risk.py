from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from trinol.core.authz.permissions import Permission
from trinol.core.authz.require import require
from trinol.core.db.engine import get_db_session
from trinol.modules.ai.schemas import ProjectRiskListResponse, ProjectRiskResponse
from trinol.modules.ai.services.client import AIClient
from trinol.modules.ai.services.deps import get_ai_client
from trinol.modules.ai.services.project_risk_service import (
    ProjectRisk,
    get_project_risk,
    list_project_risk,
)
from trinol.modules.identity.deps import get_current_membership
from trinol.modules.identity.models import Membership

# GET /ai/project-risk (org-wide) lives here, not routes/reindex.py or
# search.py — same "/ai/..." prefix, different resource, same shape
# assistant.py/search.py already use.
ai_router = APIRouter(prefix="/api/v1/ai", tags=["ai"])
# GET /projects/{project_id}/risk is a project sub-resource, matching
# projects/analytics's own "/projects/..." prefix precedent (Phase 7).
project_router = APIRouter(prefix="/api/v1/projects", tags=["ai"])


def _to_response(risk: ProjectRisk) -> ProjectRiskResponse:
    return ProjectRiskResponse(
        project_id=risk.project_id,
        project_name=risk.project_name,
        level=risk.level,
        narrative=risk.narrative,
        computed_at=risk.computed_at,
    )


@project_router.get(
    "/{project_id}/risk",
    response_model=ProjectRiskResponse,
    dependencies=[Depends(require(Permission.PROJECT_READ))],
)
async def get_project_risk_route(
    project_id: uuid.UUID,
    membership: Membership = Depends(get_current_membership),
    db: AsyncSession = Depends(get_db_session),
    ai_client: AIClient = Depends(get_ai_client),
) -> ProjectRiskResponse:
    risk = await get_project_risk(
        db,
        organization_id=membership.organization_id,
        actor=membership,
        project_id=project_id,
        ai_client=ai_client,
    )
    return _to_response(risk)


@ai_router.get(
    "/project-risk",
    response_model=ProjectRiskListResponse,
    dependencies=[Depends(require(Permission.PROJECT_READ))],
)
async def list_project_risk_route(
    membership: Membership = Depends(get_current_membership),
    db: AsyncSession = Depends(get_db_session),
) -> ProjectRiskListResponse:
    risks = await list_project_risk(
        db, organization_id=membership.organization_id, actor=membership
    )
    return ProjectRiskListResponse(items=[_to_response(r) for r in risks])

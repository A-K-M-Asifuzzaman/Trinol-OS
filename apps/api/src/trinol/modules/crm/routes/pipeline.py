from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from trinol.core.authz.permissions import Permission
from trinol.core.authz.require import require
from trinol.core.db.engine import get_db_session
from trinol.modules.crm.models import LeadStage
from trinol.modules.crm.routes.leads import lead_to_response
from trinol.modules.crm.schemas import PipelineBoardResponse, PipelineColumn
from trinol.modules.crm.services.pipeline_service import get_pipeline_board
from trinol.modules.identity.deps import get_current_membership
from trinol.modules.identity.models import Membership

# No parent resource (unlike the project Kanban board, nested under
# /projects/{id}/board) — pipeline is org-wide, so it's its own top-level
# route rather than living under /leads.
router = APIRouter(prefix="/api/v1/pipeline", tags=["crm"])


@router.get(
    "", response_model=PipelineBoardResponse, dependencies=[Depends(require(Permission.LEAD_READ))]
)
async def get_pipeline_board_route(
    membership: Membership = Depends(get_current_membership),
    db: AsyncSession = Depends(get_db_session),
) -> PipelineBoardResponse:
    board = await get_pipeline_board(
        db, organization_id=membership.organization_id, actor=membership
    )
    return PipelineBoardResponse(
        columns=[
            PipelineColumn(
                stage=stage, leads=[lead_to_response(lead) for lead in board.columns[stage]]
            )
            for stage in LeadStage
        ],
        total=board.total,
        truncated=board.truncated,
    )

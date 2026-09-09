from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from trinol.core.authz.permissions import Permission
from trinol.core.authz.require import require
from trinol.core.db.engine import get_db_session
from trinol.modules.crm.routes.clients import client_to_response
from trinol.modules.crm.routes.leads import lead_to_response
from trinol.modules.identity.deps import get_current_membership
from trinol.modules.identity.models import Membership
from trinol.modules.work.routes.projects import project_to_response
from trinol.modules.work.schemas import LeadConversionResponse
from trinol.modules.work.services.lead_conversion_service import convert_lead

# Lives in `work`, not `crm` (ARCHITECTURE.md §3: crm must not import work;
# the reverse direction is the one explicitly allowed), even though the URL
# is under /leads — the RBAC gate is a CRM-facing concern, but the route's
# body is the one documented cross-module write.
router = APIRouter(prefix="/api/v1/leads", tags=["work"])


@router.post(
    "/{lead_id}/convert",
    response_model=LeadConversionResponse,
    dependencies=[Depends(require(Permission.LEAD_CONVERT))],
)
async def convert_lead_route(
    lead_id: uuid.UUID,
    membership: Membership = Depends(get_current_membership),
    db: AsyncSession = Depends(get_db_session),
) -> LeadConversionResponse:
    result = await convert_lead(
        db, organization_id=membership.organization_id, actor=membership, lead_id=lead_id
    )
    return LeadConversionResponse(
        lead=lead_to_response(result.lead),
        client=client_to_response(result.client),
        project=project_to_response(result.project),
    )

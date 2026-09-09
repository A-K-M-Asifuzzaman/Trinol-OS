from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from trinol.core.db.org_session import OrgSession
from trinol.modules.crm.models import Lead, LeadStage
from trinol.modules.crm.services.lead_service import ensure_actor_in_org
from trinol.modules.identity.models import Membership

# ROADMAP.md Phase 2 decision 3 (Kanban board), applied identically here —
# pipeline is org-wide rather than per-project, so it gets the same "bounded
# in practice, not bounded by the API" hard cap, not true pagination (a
# Kanban-style view can't sensibly paginate mid-column). Same class of
# technical debt already logged in ROADMAP.md's ledger for the task board,
# not a fresh judgment call.
_PIPELINE_LEAD_CAP = 500


@dataclass(frozen=True, slots=True)
class PipelineBoard:
    columns: dict[LeadStage, list[Lead]]
    total: int
    truncated: bool


async def get_pipeline_board(
    db: AsyncSession, *, organization_id: uuid.UUID, actor: Membership
) -> PipelineBoard:
    """RBAC.md §2: "Leads & clients: view" is open to every role — no
    per-resource visibility rule to check here, unlike the project board's
    `ensure_project_visible` (there's no parent resource; a lead either
    exists in this org or doesn't). Archived leads are excluded, same as
    `list_leads`."""
    ensure_actor_in_org(actor, organization_id)

    total_result = await db.execute(
        select(func.count())
        .select_from(Lead)
        .where(Lead.organization_id == organization_id, Lead.archived_at.is_(None))
    )
    total = total_result.scalar_one()

    org_session = OrgSession(db, organization_id=organization_id)
    result = await db.execute(
        org_session.select(Lead)
        .where(Lead.archived_at.is_(None))
        .order_by(Lead.board_position.asc(), Lead.id.asc())
        .limit(_PIPELINE_LEAD_CAP)
    )
    leads = list(result.scalars().all())

    columns: dict[LeadStage, list[Lead]] = {stage: [] for stage in LeadStage}
    for lead in leads:
        columns[lead.stage].append(lead)

    return PipelineBoard(columns=columns, total=total, truncated=total > len(leads))

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from trinol.core.authz.permissions import Role
from trinol.core.db.org_session import OrgSession
from trinol.core.errors import ForbiddenError, NotFoundError
from trinol.core.ids import uuid7
from trinol.modules.identity.models import Membership
from trinol.modules.work.models import Milestone
from trinol.modules.work.services.project_service import (
    ensure_actor_in_org,
    ensure_project_visible,
    get_project_in_org,
)

_MANAGER_UP = (Role.MANAGER, Role.ADMIN, Role.OWNER)


@dataclass(frozen=True, slots=True)
class MilestoneList:
    items: list[Milestone]
    total: int


async def get_milestone_in_org(
    db: AsyncSession, *, organization_id: uuid.UUID, milestone_id: uuid.UUID
) -> Milestone:
    result = await db.execute(
        select(Milestone).where(
            Milestone.organization_id == organization_id, Milestone.id == milestone_id
        )
    )
    milestone = result.scalar_one_or_none()
    if milestone is None:
        raise NotFoundError("Milestone not found")
    return milestone


async def create_milestone(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    actor: Membership,
    project_id: uuid.UUID,
    name: str,
    description: str | None,
    due_date: date | None,
    position: int,
) -> Milestone:
    ensure_actor_in_org(actor, organization_id)
    project = await get_project_in_org(db, organization_id=organization_id, project_id=project_id)
    await ensure_project_visible(db, project=project, actor=actor)
    # Milestones aren't a separate RBAC.md §2 matrix row — they're
    # structural project data, so they follow "Create/edit projects"
    # (MANAGER+), not decision 6's project-member-management ownership
    # exception. RBAC.md §3 documents that exception only for
    # project_members specifically; extending it here would be inventing
    # a rule the spec doesn't state.
    if actor.role not in _MANAGER_UP:
        raise ForbiddenError("Insufficient role to create a milestone")

    org_session = OrgSession(db, organization_id=organization_id)
    milestone = Milestone(
        id=uuid7(),
        project_id=project_id,
        name=name,
        description=description,
        due_date=due_date,
        position=position,
    )
    org_session.add(milestone)
    await db.commit()
    return milestone


async def list_milestones(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    actor: Membership,
    project_id: uuid.UUID,
    limit: int = 50,
    offset: int = 0,
) -> MilestoneList:
    ensure_actor_in_org(actor, organization_id)
    project = await get_project_in_org(db, organization_id=organization_id, project_id=project_id)
    await ensure_project_visible(db, project=project, actor=actor)

    total_result = await db.execute(
        select(func.count())
        .select_from(Milestone)
        .where(Milestone.organization_id == organization_id, Milestone.project_id == project_id)
    )
    total = total_result.scalar_one()

    org_session = OrgSession(db, organization_id=organization_id)
    result = await db.execute(
        org_session.select(Milestone)
        .where(Milestone.project_id == project_id)
        .order_by(Milestone.position.asc(), Milestone.id.asc())
        .limit(limit)
        .offset(offset)
    )
    return MilestoneList(items=list(result.scalars().all()), total=total)

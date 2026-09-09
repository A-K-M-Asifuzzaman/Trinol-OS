from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from trinol.core.db.org_session import OrgSession
from trinol.modules.identity.models import Membership
from trinol.modules.work.models import Task, TaskStatus
from trinol.modules.work.services.project_service import (
    ensure_actor_in_org,
    ensure_project_visible,
    get_project_in_org,
)

# ROADMAP.md Stage 4 decision 3: a hard cap, not true pagination — a Kanban
# view can't sensibly paginate mid-column. Logged in the technical debt
# ledger as a guessed ceiling, not a measured one.
_BOARD_TASK_CAP = 500


@dataclass(frozen=True, slots=True)
class ProjectBoard:
    columns: dict[TaskStatus, list[Task]]
    total: int
    truncated: bool


async def get_project_board(
    db: AsyncSession, *, organization_id: uuid.UUID, actor: Membership, project_id: uuid.UUID
) -> ProjectBoard:
    """RBAC.md §3 'Project detail' visibility rule, same as get_project —
    the board is just another view of the project's own data."""
    ensure_actor_in_org(actor, organization_id)
    project = await get_project_in_org(db, organization_id=organization_id, project_id=project_id)
    await ensure_project_visible(db, project=project, actor=actor)

    total_result = await db.execute(
        select(func.count())
        .select_from(Task)
        .where(Task.organization_id == organization_id, Task.project_id == project_id)
    )
    total = total_result.scalar_one()

    org_session = OrgSession(db, organization_id=organization_id)
    result = await db.execute(
        org_session.select(Task)
        .where(Task.project_id == project_id)
        .order_by(Task.board_position.asc(), Task.id.asc())
        .limit(_BOARD_TASK_CAP)
    )
    tasks = list(result.scalars().all())

    columns: dict[TaskStatus, list[Task]] = {status: [] for status in TaskStatus}
    for task in tasks:
        columns[task.status].append(task)

    return ProjectBoard(columns=columns, total=total, truncated=total > len(tasks))

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from trinol.modules.identity.models import Membership
from trinol.modules.work.models import Project, ProjectStatus, Task, TaskStatus
from trinol.modules.work.services.project_service import ensure_actor_in_org

# Phase 7 plan decisions 2/3/7: task completion excludes CANCELLED tasks
# from the denominator entirely (never DONE, never "not done" — the same
# reasoning invoices' own CANCELLED status is excluded from is_overdue's
# derivation); overdue uses the exact predicate shape Invoice.is_overdue
# already uses (open states AND due_date < today); the per-project
# breakdown is one GROUP BY query, not a per-project loop (mirrors
# finance's own expense_breakdown GROUP BY category). No new module (see
# plan Context) — this lives in `work` because it needs only `work`'s own
# data (Project, Task).

_OPEN_TASK_STATUSES = (TaskStatus.TODO, TaskStatus.IN_PROGRESS, TaskStatus.REVIEW)


@dataclass(frozen=True, slots=True)
class ProjectAnalyticsRow:
    project_id: uuid.UUID
    name: str
    status: ProjectStatus
    task_completion_rate: float | None
    overdue_tasks_count: int


@dataclass(frozen=True, slots=True)
class ProjectAnalytics:
    active_projects_count: int
    task_completion_rate: float | None
    overdue_tasks_count: int
    projects: list[ProjectAnalyticsRow]


async def get_project_analytics(
    db: AsyncSession, *, organization_id: uuid.UUID, actor: Membership
) -> ProjectAnalytics:
    """MASTER_PROMPT §31's "project completion"/"task completion"/
    "overdue tasks" — the one genuinely new aggregate this phase needs
    (Phase 7 plan Context: no prior implementation exists anywhere,
    despite `Project`'s own docstring and TESTING.md §2 both naming
    "progress"/"project progress" as a derived-on-read intention).
    RBAC.md §2: gated `PROJECT_READ` only (route-level) — no
    ownership-split, same "flat permission is the whole story" shape
    `get_finance_stats`/`get_lead_stats` already established for a
    read-only aggregate."""
    ensure_actor_in_org(actor, organization_id)

    active_projects_result = await db.execute(
        select(func.count())
        .select_from(Project)
        .where(Project.organization_id == organization_id, Project.status == ProjectStatus.ACTIVE)
    )
    active_projects_count = active_projects_result.scalar_one()

    today = date.today()
    org_wide_result = await db.execute(
        select(
            func.count().filter(Task.status == TaskStatus.DONE),
            func.count().filter(Task.status != TaskStatus.CANCELLED),
            func.count().filter(Task.status.in_(_OPEN_TASK_STATUSES), Task.due_date < today),
        ).where(Task.organization_id == organization_id)
    )
    done_count, non_cancelled_count, overdue_tasks_count = org_wide_result.one()
    task_completion_rate = (done_count / non_cancelled_count) if non_cancelled_count else None

    # One LEFT JOIN + GROUP BY, not a per-project loop (decision 7) — a
    # project with zero tasks still appears (rate=None, overdue=0) since
    # the join keeps every project row regardless of a Task match.
    per_project_result = await db.execute(
        select(
            Project.id,
            Project.name,
            Project.status,
            func.count().filter(Task.status == TaskStatus.DONE),
            func.count().filter(Task.status != TaskStatus.CANCELLED),
            func.count().filter(Task.status.in_(_OPEN_TASK_STATUSES), Task.due_date < today),
        )
        .select_from(Project)
        .outerjoin(
            Task,
            and_(Task.organization_id == Project.organization_id, Task.project_id == Project.id),
        )
        .where(Project.organization_id == organization_id, Project.archived_at.is_(None))
        .group_by(Project.id, Project.name, Project.status)
        .order_by(Project.name)
    )
    projects = [
        ProjectAnalyticsRow(
            project_id=row_id,
            name=name,
            status=status,
            task_completion_rate=(row_done / row_non_cancelled) if row_non_cancelled else None,
            overdue_tasks_count=row_overdue,
        )
        for row_id, name, status, row_done, row_non_cancelled, row_overdue in (
            per_project_result.all()
        )
    ]

    return ProjectAnalytics(
        active_projects_count=active_projects_count,
        task_completion_rate=task_completion_rate,
        overdue_tasks_count=overdue_tasks_count,
        projects=projects,
    )

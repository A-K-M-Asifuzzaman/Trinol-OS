from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from trinol.core.authz.permissions import Role
from trinol.modules.identity.models import Membership
from trinol.modules.work.models import Project, ProjectMember, ProjectStatus, Task, TaskStatus
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
#
# Codex Stage 1 P1 (real, fixed): the first version gated this whole
# response on PROJECT_READ alone, reusing finance/lead stats' own "no
# ownership-split" precedent — but that precedent is Finance/CRM's, not
# Work's own. `project_service.py`'s `ensure_project_visible`/
# `list_projects` already establish a real per-resource rule (RBAC.md §3
# "Project detail": MANAGER+ or `project_members` membership), and
# `list_projects` filters its own `total` by that rule too, not just its
# item rows — so a Project-identifying aggregate here must do the same.
# `list_tasks`, by contrast, is documented as deliberately org-wide
# transparency with *no* per-resource restriction (its own docstring:
# "read is org-wide transparency here... only editing is
# ownership-restricted") — so the two org-wide *task* aggregates below
# (which never name a project) stay genuinely company-wide; only the
# Project-identifying pieces (the active-project count and the
# per-project breakdown rows) apply the same visibility filter
# `list_projects` already uses.

_MANAGER_UP = (Role.MANAGER, Role.ADMIN, Role.OWNER)
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
    `PROJECT_READ` (route-level) admits everyone; visibility of any
    specific *project* is still `ensure_project_visible`'s own rule
    (module docstring above) — a MEMBER only sees active-project counts
    and per-project rows for projects they belong to, same as
    `list_projects`. The two task-only aggregates stay org-wide, matching
    `list_tasks`'s own documented no-ownership-split precedent."""
    ensure_actor_in_org(actor, organization_id)

    sees_all_projects = actor.role in _MANAGER_UP
    visible_project_ids: list[uuid.UUID] = []
    if not sees_all_projects:
        member_rows = await db.execute(
            select(ProjectMember.project_id).where(
                ProjectMember.organization_id == organization_id,
                ProjectMember.user_id == actor.user_id,
            )
        )
        visible_project_ids = [row[0] for row in member_rows.all()]

    active_projects_filters = [
        Project.organization_id == organization_id,
        Project.status == ProjectStatus.ACTIVE,
    ]
    if not sees_all_projects:
        active_projects_filters.append(Project.id.in_(visible_project_ids))
    active_projects_result = await db.execute(
        select(func.count()).select_from(Project).where(*active_projects_filters)
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
    per_project_filters = [
        Project.organization_id == organization_id,
        Project.archived_at.is_(None),
    ]
    if not sees_all_projects:
        per_project_filters.append(Project.id.in_(visible_project_ids))
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
        .where(*per_project_filters)
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

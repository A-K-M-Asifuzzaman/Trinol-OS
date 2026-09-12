from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from trinol.core.db.org_session import OrgSession
from trinol.core.ids import uuid7
from trinol.modules.ai.models import ProjectRiskAssessment, ProjectRiskLevel
from trinol.modules.ai.services.client import AIClient
from trinol.modules.ai.services.embedding_service import ensure_actor_in_org
from trinol.modules.identity.models import Membership
from trinol.modules.work.models import Project, ProjectHealth, ProjectStatus
from trinol.modules.work.services.analytics_service import (
    ProjectAnalyticsRow,
    get_project_analytics,
)
from trinol.modules.work.services.project_service import ensure_project_visible, get_project_in_org

# Phase 8 Stage 6: `level` is always a fixed threshold rule over
# work.services.analytics_service.get_project_analytics() output plus
# Project.health/deadline -- never the LLM (ADR-0014's generalization of
# MASTER_PROMPT §30's "no LLM financial totals" rule to any figure this
# project's leadership would treat as authoritative). Only `narrative`
# (the prose explaining `level`) is LLM-authored, and only regenerated
# when the signals actually changed since the cached row.

_HIGH_OVERDUE_THRESHOLD = 3
_MEDIUM_OVERDUE_THRESHOLD = 1
_LOW_COMPLETION_THRESHOLD = 0.5

_SYSTEM_PROMPT = (
    "You write a short, one-paragraph explanation of why an internal "
    "company project has been assessed at a given risk level. You are "
    "given the risk level and the signals it was computed from -- do "
    "not recompute or contradict the level, just explain it in plain "
    "language for the team. Only use the information given."
)


@dataclass(frozen=True, slots=True)
class ProjectRisk:
    project_id: uuid.UUID
    project_name: str
    level: ProjectRiskLevel
    narrative: str | None
    computed_at: datetime | None


def _signals_snapshot(
    *, project: Project, task_completion_rate: float | None, overdue_tasks_count: int
) -> dict[str, object]:
    return {
        "status": project.status.value,
        "health": project.health.value,
        "deadline": project.deadline.isoformat() if project.deadline else None,
        "task_completion_rate": task_completion_rate,
        "overdue_tasks_count": overdue_tasks_count,
    }


def _compute_level(
    *, project: Project, task_completion_rate: float | None, overdue_tasks_count: int
) -> ProjectRiskLevel:
    deadline_passed = (
        project.deadline is not None
        and project.deadline < date.today()
        and project.status == ProjectStatus.ACTIVE
    )
    if (
        project.health == ProjectHealth.DELAYED
        or deadline_passed
        or overdue_tasks_count >= _HIGH_OVERDUE_THRESHOLD
    ):
        return ProjectRiskLevel.HIGH
    if (
        project.health == ProjectHealth.AT_RISK
        or overdue_tasks_count >= _MEDIUM_OVERDUE_THRESHOLD
        or (task_completion_rate is not None and task_completion_rate < _LOW_COMPLETION_THRESHOLD)
    ):
        return ProjectRiskLevel.MEDIUM
    return ProjectRiskLevel.LOW


def _build_prompt(*, project: Project, level: ProjectRiskLevel, snapshot: dict[str, object]) -> str:
    return (
        f"Project: {project.name}\n"
        f"Assessed risk level: {level.value}\n"
        f"Status: {snapshot['status']}\n"
        f"Health: {snapshot['health']}\n"
        f"Deadline: {snapshot['deadline'] or '(none set)'}\n"
        f"Task completion rate: {snapshot['task_completion_rate']}\n"
        f"Overdue tasks: {snapshot['overdue_tasks_count']}"
    )


async def _get_assessment_row(
    db: AsyncSession, *, organization_id: uuid.UUID, project_id: uuid.UUID
) -> ProjectRiskAssessment | None:
    org_session = OrgSession(db, organization_id=organization_id)
    result = await db.execute(
        org_session.select(ProjectRiskAssessment).where(
            ProjectRiskAssessment.project_id == project_id
        )
    )
    return result.scalar_one_or_none()


def _row_for_project(
    projects: list[ProjectAnalyticsRow], *, project_id: uuid.UUID
) -> ProjectAnalyticsRow | None:
    return next((row for row in projects if row.project_id == project_id), None)


async def get_project_risk(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    actor: Membership,
    project_id: uuid.UUID,
    ai_client: AIClient,
) -> ProjectRisk:
    """Reuses `project_service`'s own visibility rule (`ensure_project_
    visible`) — same as every other single-project route. `level` is
    always fresh; `narrative` is regenerated only when `signals_
    snapshot` no longer matches (bounded to at most one LLM call per
    read, never more)."""
    ensure_actor_in_org(actor, organization_id)
    project = await get_project_in_org(db, organization_id=organization_id, project_id=project_id)
    await ensure_project_visible(db, project=project, actor=actor)

    analytics = await get_project_analytics(db, organization_id=organization_id, actor=actor)
    row = _row_for_project(analytics.projects, project_id=project_id)
    task_completion_rate = row.task_completion_rate if row is not None else None
    overdue_tasks_count = row.overdue_tasks_count if row is not None else 0

    level = _compute_level(
        project=project,
        task_completion_rate=task_completion_rate,
        overdue_tasks_count=overdue_tasks_count,
    )
    snapshot = _signals_snapshot(
        project=project,
        task_completion_rate=task_completion_rate,
        overdue_tasks_count=overdue_tasks_count,
    )

    existing = await _get_assessment_row(db, organization_id=organization_id, project_id=project_id)
    if existing is not None and existing.signals_snapshot == snapshot:
        return ProjectRisk(
            project_id=project_id,
            project_name=project.name,
            level=level,
            narrative=existing.narrative,
            computed_at=existing.computed_at,
        )

    prompt = _build_prompt(project=project, level=level, snapshot=snapshot)
    narrative = await ai_client.complete(system=_SYSTEM_PROMPT, prompt=prompt)
    now = datetime.now(UTC)

    if existing is None:
        org_session = OrgSession(db, organization_id=organization_id)
        existing = ProjectRiskAssessment(
            id=uuid7(),
            project_id=project_id,
            level=level,
            narrative=narrative,
            signals_snapshot=snapshot,
            computed_at=now,
        )
        org_session.add(existing)
    else:
        existing.level = level
        existing.narrative = narrative
        existing.signals_snapshot = snapshot
        existing.computed_at = now

    await db.commit()
    return ProjectRisk(
        project_id=project_id,
        project_name=project.name,
        level=level,
        narrative=narrative,
        computed_at=now,
    )


async def list_project_risk(
    db: AsyncSession, *, organization_id: uuid.UUID, actor: Membership
) -> list[ProjectRisk]:
    """Org-wide view — same `MEMBER`-sees-own/`MANAGER+`-sees-all filter
    `get_project_analytics` already establishes (it's the source of the
    project list here). Deliberately never calls the AI provider: a
    list of every project's risk would otherwise risk one real API call
    per project on a single page load. `level` is always fresh; only
    whatever `narrative` is already cached is returned (`None` for a
    project never assessed via the single-project route) — regenerating
    it is `get_project_risk`'s job, triggered by an explicit single-
    project view, not this list."""
    ensure_actor_in_org(actor, organization_id)
    analytics = await get_project_analytics(db, organization_id=organization_id, actor=actor)
    project_ids = [row.project_id for row in analytics.projects]

    # One bulk fetch for health/deadline/status, not one query per
    # project (analytics.projects itself already has name/status but not
    # health/deadline) -- avoids an N+1 pattern for what could be a
    # non-trivial project count.
    projects_result = await db.execute(
        select(Project).where(
            Project.organization_id == organization_id, Project.id.in_(project_ids)
        )
    )
    projects_by_id = {project.id: project for project in projects_result.scalars().all()}

    org_session = OrgSession(db, organization_id=organization_id)
    assessments_result = await db.execute(
        org_session.select(ProjectRiskAssessment).where(
            ProjectRiskAssessment.project_id.in_(project_ids)
        )
    )
    assessments_by_project_id = {
        assessment.project_id: assessment for assessment in assessments_result.scalars().all()
    }

    results: list[ProjectRisk] = []
    for row in analytics.projects:
        project = projects_by_id.get(row.project_id)
        if project is None:
            continue
        level = _compute_level(
            project=project,
            task_completion_rate=row.task_completion_rate,
            overdue_tasks_count=row.overdue_tasks_count,
        )
        existing = assessments_by_project_id.get(row.project_id)
        results.append(
            ProjectRisk(
                project_id=row.project_id,
                project_name=row.name,
                level=level,
                narrative=existing.narrative if existing is not None else None,
                computed_at=existing.computed_at if existing is not None else None,
            )
        )
    return results

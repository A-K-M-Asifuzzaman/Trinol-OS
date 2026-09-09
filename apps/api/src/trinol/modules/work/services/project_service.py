from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from trinol.core.authz.permissions import Role
from trinol.core.db.org_session import OrgSession
from trinol.core.errors import AppError, ConflictError, ForbiddenError, NotFoundError
from trinol.core.ids import uuid7
from trinol.modules.identity.models import Membership, MembershipStatus
from trinol.modules.work.models import (
    Project,
    ProjectHealth,
    ProjectMember,
    ProjectStatus,
    RoleOnProject,
)

_MANAGER_UP = (Role.MANAGER, Role.ADMIN, Role.OWNER)


@dataclass(frozen=True, slots=True)
class ProjectList:
    items: list[Project]
    total: int


def ensure_actor_in_org(actor: Membership, organization_id: uuid.UUID) -> None:
    """Defense in depth, shared by every work-module service — the route-
    level require(...) gate and get_current_membership are what make this
    true in practice, but no service function can verify either happened
    (same reasoning as identity's _ensure_actor_can_act/_ensure_actor_in_org)."""
    if actor.organization_id != organization_id:
        raise ForbiddenError("Actor does not belong to this organization")


async def get_active_membership_by_user(
    db: AsyncSession, *, organization_id: uuid.UUID, user_id: uuid.UUID
) -> Membership:
    result = await db.execute(
        select(Membership).where(
            Membership.organization_id == organization_id,
            Membership.user_id == user_id,
            Membership.status == MembershipStatus.ACTIVE,
        )
    )
    membership = result.scalar_one_or_none()
    if membership is None:
        raise AppError("user_id must reference an active membership in this organization")
    return membership


async def get_project_in_org(
    db: AsyncSession, *, organization_id: uuid.UUID, project_id: uuid.UUID
) -> Project:
    """Org-scoped lookup — 404s a cross-org id exactly like a missing one
    (RBAC.md §4), same pattern as identity's get_membership_in_org."""
    result = await db.execute(
        select(Project).where(Project.organization_id == organization_id, Project.id == project_id)
    )
    project = result.scalar_one_or_none()
    if project is None:
        raise NotFoundError("Project not found")
    return project


async def is_project_member(
    db: AsyncSession, *, organization_id: uuid.UUID, project_id: uuid.UUID, user_id: uuid.UUID
) -> bool:
    result = await db.execute(
        select(ProjectMember.id).where(
            ProjectMember.organization_id == organization_id,
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == user_id,
        )
    )
    return result.scalar_one_or_none() is not None


async def ensure_project_visible(db: AsyncSession, *, project: Project, actor: Membership) -> None:
    """RBAC.md §3 'Project detail' rule: MANAGER+ or membership in
    project_members. create_project always adds the owner to
    project_members (as LEAD), so that's the single, uniform visibility
    check — no separate project.owner_id branch needed here."""
    if actor.role in _MANAGER_UP:
        return
    if await is_project_member(
        db, organization_id=actor.organization_id, project_id=project.id, user_id=actor.user_id
    ):
        return
    raise ForbiddenError("Not a member of this project")


def can_manage_members(actor: Membership, project: Project) -> bool:
    """ROADMAP.md Phase 2 decision 6 / RBAC.md §3: MANAGER+ or the project's
    own owner. The route already admits every role via PROJECT_MEMBER_WRITE
    (MEMBER-tier, reachability only) — this is the real check."""
    return actor.role in _MANAGER_UP or project.owner_id == actor.user_id


async def create_project(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    actor: Membership,
    project_code: str,
    name: str,
    description: str | None,
    status: ProjectStatus,
    health: ProjectHealth,
    owner_id: uuid.UUID | None,
    start_date: Any,
    deadline: Any,
    budget: Any,
    currency: str,
    repository_url: str | None,
    production_url: str | None,
    staging_url: str | None,
) -> Project:
    ensure_actor_in_org(actor, organization_id)
    if actor.role not in _MANAGER_UP:
        raise ForbiddenError("Insufficient role to create a project")

    resolved_owner_id = owner_id if owner_id is not None else actor.user_id
    await get_active_membership_by_user(
        db, organization_id=organization_id, user_id=resolved_owner_id
    )

    existing = await db.execute(
        select(Project.id).where(
            Project.organization_id == organization_id, Project.project_code == project_code
        )
    )
    if existing.scalar_one_or_none() is not None:
        raise ConflictError("project_code already in use in this organization")

    org_session = OrgSession(db, organization_id=organization_id)
    project = Project(
        id=uuid7(),
        project_code=project_code,
        name=name,
        description=description,
        status=status,
        health=health,
        owner_id=resolved_owner_id,
        start_date=start_date,
        deadline=deadline,
        budget=budget,
        currency=currency,
        repository_url=repository_url,
        production_url=production_url,
        staging_url=staging_url,
    )
    org_session.add(project)
    await db.flush()

    # The owner is always a project_members row (LEAD) — see
    # ensure_project_visible's docstring.
    org_session.add(
        ProjectMember(
            id=uuid7(),
            project_id=project.id,
            user_id=resolved_owner_id,
            role_on_project=RoleOnProject.LEAD,
        )
    )
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise ConflictError("project_code already in use in this organization") from None
    return project


async def list_projects(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    actor: Membership,
    limit: int = 50,
    offset: int = 0,
) -> ProjectList:
    ensure_actor_in_org(actor, organization_id)

    # ADR-0011: the list endpoint excludes archived rows.
    base_filters: list[Any] = [Project.archived_at.is_(None)]
    if actor.role not in _MANAGER_UP:
        # RBAC.md §3's "Project detail" visibility rule, applied uniformly
        # to the list too — otherwise a MEMBER could read project fields
        # off the list response for a project they can't open.
        member_rows = await db.execute(
            select(ProjectMember.project_id).where(
                ProjectMember.organization_id == organization_id,
                ProjectMember.user_id == actor.user_id,
            )
        )
        member_project_ids = [row[0] for row in member_rows.all()]
        base_filters.append(Project.id.in_(member_project_ids))

    total_result = await db.execute(
        select(func.count())
        .select_from(Project)
        .where(Project.organization_id == organization_id, *base_filters)
    )
    total = total_result.scalar_one()

    org_session = OrgSession(db, organization_id=organization_id)
    result = await db.execute(
        org_session.select(Project)
        .where(*base_filters)
        .order_by(Project.created_at.asc(), Project.id.asc())
        .limit(limit)
        .offset(offset)
    )
    return ProjectList(items=list(result.scalars().all()), total=total)


async def get_project(
    db: AsyncSession, *, organization_id: uuid.UUID, actor: Membership, project_id: uuid.UUID
) -> Project:
    ensure_actor_in_org(actor, organization_id)
    project = await get_project_in_org(db, organization_id=organization_id, project_id=project_id)
    await ensure_project_visible(db, project=project, actor=actor)
    return project


async def update_project(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    actor: Membership,
    project_id: uuid.UUID,
    updates: dict[str, Any],
) -> Project:
    ensure_actor_in_org(actor, organization_id)
    if actor.role not in _MANAGER_UP:
        raise ForbiddenError("Insufficient role to edit this project")
    project = await get_project_in_org(db, organization_id=organization_id, project_id=project_id)

    for field, value in updates.items():
        setattr(project, field, value)

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise ConflictError("project_code already in use in this organization") from None
    return project


async def archive_project(
    db: AsyncSession, *, organization_id: uuid.UUID, actor: Membership, project_id: uuid.UUID
) -> Project:
    """DELETE archives (ADR-0011), never a SQL DELETE. No restore endpoint
    yet — not requested; `archived_at` is a plain column a future PATCH
    could clear if that becomes a real requirement."""
    ensure_actor_in_org(actor, organization_id)
    if actor.role not in (Role.ADMIN, Role.OWNER):
        raise ForbiddenError("Insufficient role to delete this project")
    project = await get_project_in_org(db, organization_id=organization_id, project_id=project_id)
    project.archived_at = datetime.now(UTC)
    await db.commit()
    return project

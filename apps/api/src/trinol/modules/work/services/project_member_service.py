from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from trinol.core.db.org_session import OrgSession
from trinol.core.errors import ConflictError, ForbiddenError, NotFoundError
from trinol.core.ids import uuid7
from trinol.modules.identity.models import Membership
from trinol.modules.work.models import ProjectMember, RoleOnProject
from trinol.modules.work.services.project_service import (
    can_manage_members,
    ensure_actor_in_org,
    ensure_project_visible,
    get_active_membership_by_user,
    get_project_in_org,
)


@dataclass(frozen=True, slots=True)
class ProjectMemberList:
    items: list[ProjectMember]
    total: int


async def get_project_member_in_org(
    db: AsyncSession, *, organization_id: uuid.UUID, project_id: uuid.UUID, member_id: uuid.UUID
) -> ProjectMember:
    result = await db.execute(
        select(ProjectMember).where(
            ProjectMember.organization_id == organization_id,
            ProjectMember.project_id == project_id,
            ProjectMember.id == member_id,
        )
    )
    member = result.scalar_one_or_none()
    if member is None:
        raise NotFoundError("Project member not found")
    return member


async def list_project_members(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    actor: Membership,
    project_id: uuid.UUID,
    limit: int = 50,
    offset: int = 0,
) -> ProjectMemberList:
    ensure_actor_in_org(actor, organization_id)
    project = await get_project_in_org(db, organization_id=organization_id, project_id=project_id)
    await ensure_project_visible(db, project=project, actor=actor)

    total_result = await db.execute(
        select(func.count())
        .select_from(ProjectMember)
        .where(
            ProjectMember.organization_id == organization_id,
            ProjectMember.project_id == project_id,
        )
    )
    total = total_result.scalar_one()

    org_session = OrgSession(db, organization_id=organization_id)
    result = await db.execute(
        org_session.select(ProjectMember)
        .where(ProjectMember.project_id == project_id)
        .order_by(ProjectMember.added_at.asc(), ProjectMember.id.asc())
        .limit(limit)
        .offset(offset)
    )
    return ProjectMemberList(items=list(result.scalars().all()), total=total)


async def add_project_member(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    actor: Membership,
    project_id: uuid.UUID,
    user_id: uuid.UUID,
    role_on_project: RoleOnProject,
) -> ProjectMember:
    ensure_actor_in_org(actor, organization_id)
    project = await get_project_in_org(db, organization_id=organization_id, project_id=project_id)
    if not can_manage_members(actor, project):
        raise ForbiddenError("Insufficient permission to manage this project's members")

    await get_active_membership_by_user(db, organization_id=organization_id, user_id=user_id)

    existing = await db.execute(
        select(ProjectMember.id).where(
            ProjectMember.organization_id == organization_id,
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == user_id,
        )
    )
    if existing.scalar_one_or_none() is not None:
        raise ConflictError("User is already a member of this project")

    org_session = OrgSession(db, organization_id=organization_id)
    member = ProjectMember(
        id=uuid7(), project_id=project_id, user_id=user_id, role_on_project=role_on_project
    )
    org_session.add(member)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise ConflictError("User is already a member of this project") from None
    return member


async def update_project_member(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    actor: Membership,
    project_id: uuid.UUID,
    member_id: uuid.UUID,
    role_on_project: RoleOnProject,
) -> ProjectMember:
    ensure_actor_in_org(actor, organization_id)
    project = await get_project_in_org(db, organization_id=organization_id, project_id=project_id)
    if not can_manage_members(actor, project):
        raise ForbiddenError("Insufficient permission to manage this project's members")

    member = await get_project_member_in_org(
        db, organization_id=organization_id, project_id=project_id, member_id=member_id
    )
    member.role_on_project = role_on_project
    await db.commit()
    return member


async def remove_project_member(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    actor: Membership,
    project_id: uuid.UUID,
    member_id: uuid.UUID,
) -> None:
    ensure_actor_in_org(actor, organization_id)
    project = await get_project_in_org(db, organization_id=organization_id, project_id=project_id)
    if not can_manage_members(actor, project):
        raise ForbiddenError("Insufficient permission to manage this project's members")

    member = await get_project_member_in_org(
        db, organization_id=organization_id, project_id=project_id, member_id=member_id
    )
    if member.user_id == project.owner_id:
        # Keeps ensure_project_visible's invariant intact (the owner is
        # always a project_members row) rather than special-casing
        # visibility for an owner with no roster row.
        raise ConflictError("Cannot remove the project owner; reassign ownership first")

    await db.delete(member)
    await db.commit()

"""`make seed` — Phase 1 plan decision 6, extended by Phase 2 decision 4.

One organization (the real company, `trinolit`) with three placeholder
users named after MASTER_PROMPT §36's role hints (Founder/Developer/
Designer) under the real `@trinolit.com` domain. These are structural
placeholders, not real accounts: no Firebase user exists for them yet, so
nobody can actually sign in as one until real accounts are created and their
`firebase_uid` is updated to match. Trivially edited later.

Phase 2 decision 4: two realistic projects, not MASTER_PROMPT §36's full
list (3-5 clients is a Phase 3/CRM concept `projects.client_id` doesn't
have anything to reference yet) — "TrinolIT Website" and an internal-
product project ("Trinol OS" itself, dogfooding), each with a spread of
tasks across every status/priority, enough to exercise the Kanban board and
dashboard tiles realistically. MASTER_PROMPT §36 also asks for clients,
leads, invoices, and meetings — none of those tables exist yet (Phase 3+),
so they're not part of this script. Add them here when their phase lands.

Idempotent: re-running never duplicates a row, matched on the organization's
slug, each user's email, the (organization, user) membership pair, each
project's code, each (project, user) project-member pair, and each
(project, title) task pair.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from trinol.core.authz.permissions import Role
from trinol.core.db.engine import get_session_factory
from trinol.core.db.org_session import register_org_scope_guard
from trinol.core.ids import uuid7
from trinol.modules.identity.models import (
    AuthProvider,
    Membership,
    MembershipStatus,
    Organization,
    User,
)
from trinol.modules.work.models import (
    Project,
    ProjectMember,
    RoleOnProject,
    Task,
    TaskPriority,
    TaskStatus,
)

# Imported for its side effect of registering file_objects on Base.metadata
# (same reasoning as migrations/env.py) — organizations.logo_file_id's
# composite FK (Stage 6) can't resolve at flush time otherwise, since this
# script's own imports above never otherwise reference platform.models.
from trinol.platform import models as _platform_models  # noqa: F401

_ORG_SLUG = "trinolit"
_ORG_NAME = "TrinolIT"


@dataclass(frozen=True, slots=True)
class _SeedUser:
    full_name: str
    email: str
    role: Role


_SEED_USERS: tuple[_SeedUser, ...] = (
    _SeedUser(full_name="Founder", email="founder@trinolit.com", role=Role.OWNER),
    _SeedUser(full_name="Developer", email="developer@trinolit.com", role=Role.MEMBER),
    _SeedUser(full_name="Designer", email="designer@trinolit.com", role=Role.MEMBER),
)
_FOUNDER_EMAIL = _SEED_USERS[0].email
_DEVELOPER_EMAIL = _SEED_USERS[1].email
_DESIGNER_EMAIL = _SEED_USERS[2].email


@dataclass(frozen=True, slots=True)
class _SeedTask:
    title: str
    status: TaskStatus
    priority: TaskPriority
    assignee_email: str


@dataclass(frozen=True, slots=True)
class _SeedProject:
    project_code: str
    name: str
    owner_email: str
    member_emails: tuple[str, ...]
    tasks: tuple[_SeedTask, ...]


_SEED_PROJECTS: tuple[_SeedProject, ...] = (
    _SeedProject(
        project_code="WEB",
        name="TrinolIT Website",
        owner_email=_FOUNDER_EMAIL,
        member_emails=(_DEVELOPER_EMAIL, _DESIGNER_EMAIL),
        tasks=(
            _SeedTask(
                "Set up hosting and domain", TaskStatus.TODO, TaskPriority.HIGH, _DEVELOPER_EMAIL
            ),
            _SeedTask(
                "Build homepage layout",
                TaskStatus.IN_PROGRESS,
                TaskPriority.HIGH,
                _DESIGNER_EMAIL,
            ),
            _SeedTask(
                "Write About page copy", TaskStatus.REVIEW, TaskPriority.MEDIUM, _FOUNDER_EMAIL
            ),
            _SeedTask("Pick color palette", TaskStatus.DONE, TaskPriority.LOW, _DESIGNER_EMAIL),
            _SeedTask(
                "Integrate legacy CMS", TaskStatus.CANCELLED, TaskPriority.URGENT, _DEVELOPER_EMAIL
            ),
        ),
    ),
    _SeedProject(
        project_code="TOS",
        name="Trinol OS",
        owner_email=_FOUNDER_EMAIL,
        member_emails=(_DEVELOPER_EMAIL, _DESIGNER_EMAIL),
        tasks=(
            _SeedTask(
                "Draft Kanban board UX", TaskStatus.TODO, TaskPriority.MEDIUM, _DESIGNER_EMAIL
            ),
            _SeedTask(
                "Wire activity feed to dashboard",
                TaskStatus.IN_PROGRESS,
                TaskPriority.HIGH,
                _DEVELOPER_EMAIL,
            ),
            _SeedTask(
                "Security review of auth flow",
                TaskStatus.REVIEW,
                TaskPriority.URGENT,
                _FOUNDER_EMAIL,
            ),
            _SeedTask(
                "Ship Phase 1 foundation", TaskStatus.DONE, TaskPriority.HIGH, _DEVELOPER_EMAIL
            ),
            _SeedTask(
                "Evaluate alternate hosting",
                TaskStatus.CANCELLED,
                TaskPriority.LOW,
                _FOUNDER_EMAIL,
            ),
        ),
    ),
)


async def _get_or_create_organization(db: AsyncSession) -> Organization:
    result = await db.execute(select(Organization).where(Organization.slug == _ORG_SLUG))
    organization = result.scalar_one_or_none()
    if organization is not None:
        return organization
    organization = Organization(id=uuid7(), name=_ORG_NAME, slug=_ORG_SLUG)
    db.add(organization)
    await db.flush()
    return organization


async def _get_or_create_user(db: AsyncSession, *, email: str, full_name: str) -> User:
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if user is not None:
        return user
    user = User(
        id=uuid7(),
        # Placeholder, not a real Firebase identity (see module docstring) —
        # distinguishable at a glance from a real "fb-..." uid.
        firebase_uid=f"seed-{email}",
        email=email,
        auth_provider=AuthProvider.PASSWORD,
        full_name=full_name,
    )
    db.add(user)
    await db.flush()
    return user


async def _ensure_membership(
    db: AsyncSession, *, organization: Organization, user: User, role: Role
) -> None:
    result = await db.execute(
        select(Membership).where(
            Membership.organization_id == organization.id, Membership.user_id == user.id
        )
    )
    if result.scalar_one_or_none() is not None:
        return
    db.add(
        Membership(
            id=uuid7(),
            organization_id=organization.id,
            user_id=user.id,
            role=role,
            status=MembershipStatus.ACTIVE,
        )
    )


async def _get_or_create_project(
    db: AsyncSession, *, organization: Organization, entry: _SeedProject, owner_user_id: uuid.UUID
) -> Project:
    result = await db.execute(
        select(Project).where(
            Project.organization_id == organization.id,
            Project.project_code == entry.project_code,
        )
    )
    project = result.scalar_one_or_none()
    if project is not None:
        return project
    project = Project(
        id=uuid7(),
        organization_id=organization.id,
        project_code=entry.project_code,
        name=entry.name,
        owner_id=owner_user_id,
    )
    db.add(project)
    await db.flush()
    return project


async def _ensure_project_member(
    db: AsyncSession, *, project: Project, user_id: uuid.UUID, role_on_project: RoleOnProject
) -> None:
    result = await db.execute(
        select(ProjectMember).where(
            ProjectMember.organization_id == project.organization_id,
            ProjectMember.project_id == project.id,
            ProjectMember.user_id == user_id,
        )
    )
    if result.scalar_one_or_none() is not None:
        return
    db.add(
        ProjectMember(
            id=uuid7(),
            organization_id=project.organization_id,
            project_id=project.id,
            user_id=user_id,
            role_on_project=role_on_project,
        )
    )


async def _ensure_task(
    db: AsyncSession,
    *,
    project: Project,
    entry: _SeedTask,
    assignee_user_id: uuid.UUID,
    created_by_user_id: uuid.UUID,
) -> None:
    result = await db.execute(
        select(Task).where(
            Task.organization_id == project.organization_id,
            Task.project_id == project.id,
            Task.title == entry.title,
        )
    )
    if result.scalar_one_or_none() is not None:
        return
    db.add(
        Task(
            id=uuid7(),
            organization_id=project.organization_id,
            project_id=project.id,
            title=entry.title,
            status=entry.status,
            priority=entry.priority,
            assignee_id=assignee_user_id,
            created_by=created_by_user_id,
            # ck_task_completed (migration 0003): a DONE task must have
            # completed_at set — same invariant task_service.create_task
            # enforces for a real request.
            completed_at=datetime.now(UTC) if entry.status == TaskStatus.DONE else None,
        )
    )


async def seed() -> None:
    register_org_scope_guard()
    session_factory = get_session_factory()
    async with session_factory() as db:
        organization = await _get_or_create_organization(db)
        users_by_email: dict[str, User] = {}
        for entry in _SEED_USERS:
            user = await _get_or_create_user(db, email=entry.email, full_name=entry.full_name)
            await _ensure_membership(db, organization=organization, user=user, role=entry.role)
            users_by_email[entry.email] = user

        for project_entry in _SEED_PROJECTS:
            owner = users_by_email[project_entry.owner_email]
            project = await _get_or_create_project(
                db, organization=organization, entry=project_entry, owner_user_id=owner.id
            )
            # Mirrors project_service.create_project's invariant: the owner
            # is always a project_members row (LEAD) — ensure_project_
            # visible relies on this being true for every project, not just
            # ones created through the API.
            await _ensure_project_member(
                db, project=project, user_id=owner.id, role_on_project=RoleOnProject.LEAD
            )
            for member_email in project_entry.member_emails:
                await _ensure_project_member(
                    db,
                    project=project,
                    user_id=users_by_email[member_email].id,
                    role_on_project=RoleOnProject.CONTRIBUTOR,
                )
            for task_entry in project_entry.tasks:
                await _ensure_task(
                    db,
                    project=project,
                    entry=task_entry,
                    assignee_user_id=users_by_email[task_entry.assignee_email].id,
                    created_by_user_id=owner.id,
                )
        await db.commit()


def main() -> None:
    asyncio.run(seed())


if __name__ == "__main__":
    main()

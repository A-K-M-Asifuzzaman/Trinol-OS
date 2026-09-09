from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from trinol.core.db.engine import get_session_factory
from trinol.core.ids import uuid7
from trinol.modules.identity.models import (
    AuthProvider,
    Membership,
    MembershipStatus,
    Organization,
    User,
)
from trinol.modules.work.models import Project, ProjectMember, Task
from trinol.scripts.seed import _ORG_SLUG, _SEED_PROJECTS, _SEED_USERS, seed

# Phase 1 plan, Stage 12 proof criterion: "make seed on a fresh DB produces
# the expected rows; re-running doesn't duplicate or error." seed() manages
# its own real session (it's a standalone CLI, not a request handler), so
# this can't use the transaction-rollback db_session fixture the rest of the
# suite relies on — same reasoning as test_escalation.py's concurrent-
# demotion test, and the same manual real-DB cleanup pattern.
#
# Codex P1 (first pass at this file): cleanup tracked only whether the
# *organization* existed, so (a) an org that already existed but was missing
# one seed user/membership left the newly-created rows behind forever, and
# (b) a seed email that already belonged to some unrelated pre-existing user
# had that user deleted out from under it. Tracked per-entity now: the
# organization, each of the three users, and each of the three memberships,
# each independently. Cleanup only ever removes what wasn't there before.
# Verified this actually catches the original bug by temporarily reverting
# to the org-existence-only check and confirming both new tests below fail
# against it.
#
# Phase 2 Stage 10: extended the same per-entity tracking to projects,
# project members, and tasks — seed() now creates those too, and an
# org-delete-only cleanup would hit `fk_projects_org_owner_memberships`
# (a project still referencing the membership being deleted), reproduced
# and fixed here the same way, not just reasoned about.


@dataclass
class _SeedSnapshot:
    organization_existed: bool
    user_existed: dict[str, bool] = field(default_factory=dict)
    membership_existed: dict[str, bool] = field(default_factory=dict)
    project_existed: dict[str, bool] = field(default_factory=dict)
    project_member_existed: dict[tuple[str, str], bool] = field(default_factory=dict)
    task_existed: dict[tuple[str, str], bool] = field(default_factory=dict)


async def _snapshot(db: AsyncSession) -> _SeedSnapshot:
    organization = (
        await db.execute(select(Organization).where(Organization.slug == _ORG_SLUG))
    ).scalar_one_or_none()

    user_existed: dict[str, bool] = {}
    user_ids: dict[str, uuid.UUID] = {}
    for entry in _SEED_USERS:
        user = (
            await db.execute(select(User).where(User.email == entry.email))
        ).scalar_one_or_none()
        user_existed[entry.email] = user is not None
        if user is not None:
            user_ids[entry.email] = user.id

    membership_existed: dict[str, bool] = {}
    for entry in _SEED_USERS:
        if organization is None or entry.email not in user_ids:
            membership_existed[entry.email] = False
            continue
        membership = (
            await db.execute(
                select(Membership).where(
                    Membership.organization_id == organization.id,
                    Membership.user_id == user_ids[entry.email],
                )
            )
        ).scalar_one_or_none()
        membership_existed[entry.email] = membership is not None

    project_existed: dict[str, bool] = {}
    project_member_existed: dict[tuple[str, str], bool] = {}
    task_existed: dict[tuple[str, str], bool] = {}
    for project_entry in _SEED_PROJECTS:
        project = None
        if organization is not None:
            project = (
                await db.execute(
                    select(Project).where(
                        Project.organization_id == organization.id,
                        Project.project_code == project_entry.project_code,
                    )
                )
            ).scalar_one_or_none()
        project_existed[project_entry.project_code] = project is not None

        for email in (project_entry.owner_email, *project_entry.member_emails):
            key = (project_entry.project_code, email)
            if project is None or email not in user_ids:
                project_member_existed[key] = False
                continue
            member = (
                await db.execute(
                    select(ProjectMember).where(
                        ProjectMember.organization_id == organization.id,
                        ProjectMember.project_id == project.id,
                        ProjectMember.user_id == user_ids[email],
                    )
                )
            ).scalar_one_or_none()
            project_member_existed[key] = member is not None

        for task_entry in project_entry.tasks:
            key = (project_entry.project_code, task_entry.title)
            if project is None:
                task_existed[key] = False
                continue
            task = (
                await db.execute(
                    select(Task).where(
                        Task.organization_id == organization.id,
                        Task.project_id == project.id,
                        Task.title == task_entry.title,
                    )
                )
            ).scalar_one_or_none()
            task_existed[key] = task is not None

    return _SeedSnapshot(
        organization_existed=organization is not None,
        user_existed=user_existed,
        membership_existed=membership_existed,
        project_existed=project_existed,
        project_member_existed=project_member_existed,
        task_existed=task_existed,
    )


async def _cleanup_rows_created_since(db: AsyncSession, snapshot: _SeedSnapshot) -> None:
    """Removes only what didn't exist in `snapshot` — a pre-existing
    organization, user, membership, project, project member, or task is
    never touched, regardless of what else this run of seed() created
    alongside it. Tasks and project members are removed before their
    project (FK dependency order), and projects before the memberships
    their owner_id references (`fk_projects_org_owner_memberships`) — the
    exact constraint a naive org-then-membership-only cleanup violates."""
    organization = (
        await db.execute(select(Organization).where(Organization.slug == _ORG_SLUG))
    ).scalar_one_or_none()

    if organization is not None:
        for project_entry in _SEED_PROJECTS:
            project = (
                await db.execute(
                    select(Project).where(
                        Project.organization_id == organization.id,
                        Project.project_code == project_entry.project_code,
                    )
                )
            ).scalar_one_or_none()
            if project is None:
                continue

            for task_entry in project_entry.tasks:
                key = (project_entry.project_code, task_entry.title)
                if snapshot.task_existed.get(key):
                    continue
                await db.execute(
                    delete(Task).where(
                        Task.organization_id == organization.id,
                        Task.project_id == project.id,
                        Task.title == task_entry.title,
                    )
                )

            for email in (project_entry.owner_email, *project_entry.member_emails):
                key = (project_entry.project_code, email)
                if snapshot.project_member_existed.get(key):
                    continue
                user = (
                    await db.execute(select(User).where(User.email == email))
                ).scalar_one_or_none()
                if user is not None:
                    await db.execute(
                        delete(ProjectMember).where(
                            ProjectMember.organization_id == organization.id,
                            ProjectMember.project_id == project.id,
                            ProjectMember.user_id == user.id,
                        )
                    )

            if not snapshot.project_existed.get(project_entry.project_code):
                await db.execute(
                    delete(Project).where(
                        Project.organization_id == organization.id, Project.id == project.id
                    )
                )

        for entry in _SEED_USERS:
            if snapshot.membership_existed.get(entry.email):
                continue
            user = (
                await db.execute(select(User).where(User.email == entry.email))
            ).scalar_one_or_none()
            if user is not None:
                await db.execute(
                    delete(Membership).where(
                        Membership.organization_id == organization.id,
                        Membership.user_id == user.id,
                    )
                )

        if not snapshot.organization_existed:
            await db.execute(delete(Organization).where(Organization.id == organization.id))

    for entry in _SEED_USERS:
        if snapshot.user_existed.get(entry.email):
            continue
        await db.execute(delete(User).where(User.email == entry.email))

    await db.commit()


async def test_seed_is_idempotent() -> None:
    session_factory = get_session_factory()
    async with session_factory() as db:
        snapshot = await _snapshot(db)

    try:
        await seed()
        await seed()

        async with session_factory() as db:
            org_result = await db.execute(
                select(Organization).where(Organization.slug == _ORG_SLUG)
            )
            organizations = org_result.scalars().all()
            assert len(organizations) == 1, "re-running must not duplicate the organization"
            organization = organizations[0]

            membership_result = await db.execute(
                select(Membership).where(Membership.organization_id == organization.id)
            )
            assert len(membership_result.scalars().all()) == len(_SEED_USERS)

            user_result = await db.execute(
                select(User).where(User.email.in_([entry.email for entry in _SEED_USERS]))
            )
            assert len(user_result.scalars().all()) == len(_SEED_USERS)

            project_result = await db.execute(
                select(Project).where(Project.organization_id == organization.id)
            )
            projects = {project.project_code: project for project in project_result.scalars()}
            assert set(projects) == {entry.project_code for entry in _SEED_PROJECTS}, (
                "re-running must not duplicate or lose a project"
            )

            for project_entry in _SEED_PROJECTS:
                project = projects[project_entry.project_code]

                member_result = await db.execute(
                    select(ProjectMember).where(
                        ProjectMember.organization_id == organization.id,
                        ProjectMember.project_id == project.id,
                    )
                )
                expected_members = 1 + len(project_entry.member_emails)  # owner + members
                assert len(member_result.scalars().all()) == expected_members, (
                    f"{project_entry.project_code}: re-running must not duplicate members"
                )

                task_result = await db.execute(
                    select(Task).where(
                        Task.organization_id == organization.id, Task.project_id == project.id
                    )
                )
                tasks = task_result.scalars().all()
                assert len(tasks) == len(project_entry.tasks), (
                    f"{project_entry.project_code}: re-running must not duplicate tasks"
                )
                assert {task.title for task in tasks} == {
                    task_entry.title for task_entry in project_entry.tasks
                }
    finally:
        async with session_factory() as db:
            await _cleanup_rows_created_since(db, snapshot)


async def test_seed_fills_in_missing_users_without_touching_a_pre_existing_org() -> None:
    """Partial state: the organization and one seed user/membership already
    exist (as if a previous seed run got that far and stopped); seed() must
    create only what's missing, and cleanup must leave the pre-existing
    organization and membership alone."""
    session_factory = get_session_factory()
    founder = _SEED_USERS[0]
    assert founder.email == "founder@trinolit.com"

    async with session_factory() as db:
        pre_snapshot = await _snapshot(db)
        assert not pre_snapshot.organization_existed, "test assumes a clean slate"

        organization = Organization(id=uuid7(), name="TrinolIT", slug=_ORG_SLUG)
        db.add(organization)
        await db.flush()
        founder_user = User(
            id=uuid7(),
            firebase_uid=f"pre-existing-{founder.email}",
            email=founder.email,
            auth_provider=AuthProvider.PASSWORD,
            full_name=founder.full_name,
        )
        db.add(founder_user)
        await db.flush()
        founder_membership = Membership(
            id=uuid7(),
            organization_id=organization.id,
            user_id=founder_user.id,
            role=founder.role,
            status=MembershipStatus.ACTIVE,
        )
        db.add(founder_membership)
        await db.commit()

        organization_id, founder_user_id, founder_membership_id = (
            organization.id,
            founder_user.id,
            founder_membership.id,
        )

    try:
        async with session_factory() as db:
            snapshot = await _snapshot(db)
        assert snapshot.organization_existed
        assert snapshot.user_existed[founder.email]
        assert snapshot.membership_existed[founder.email]
        assert not any(
            snapshot.user_existed[entry.email] for entry in _SEED_USERS if entry is not founder
        )

        await seed()

        async with session_factory() as db:
            org_result = await db.execute(
                select(Organization).where(Organization.slug == _ORG_SLUG)
            )
            assert len(org_result.scalars().all()) == 1, "must reuse, not duplicate, the org"

            user_result = await db.execute(
                select(User).where(User.email.in_([entry.email for entry in _SEED_USERS]))
            )
            assert len(user_result.scalars().all()) == len(_SEED_USERS)

            membership_result = await db.execute(
                select(Membership).where(Membership.organization_id == organization_id)
            )
            assert len(membership_result.scalars().all()) == len(_SEED_USERS)

        async with session_factory() as db:
            await _cleanup_rows_created_since(db, snapshot)

        # The pre-existing org, its Founder user, and that membership must
        # all have survived cleanup untouched.
        async with session_factory() as db:
            assert (
                await db.execute(select(Organization).where(Organization.id == organization_id))
            ).scalar_one_or_none() is not None
            assert (
                await db.execute(select(User).where(User.id == founder_user_id))
            ).scalar_one_or_none() is not None
            assert (
                await db.execute(
                    select(Membership).where(
                        Membership.organization_id == organization_id,
                        Membership.id == founder_membership_id,
                    )
                )
            ).scalar_one_or_none() is not None

            # The two seed users/memberships seed() had to create ARE gone.
            other_emails = [entry.email for entry in _SEED_USERS if entry is not founder]
            remaining_users = (
                (await db.execute(select(User).where(User.email.in_(other_emails)))).scalars().all()
            )
            assert remaining_users == []
    finally:
        async with session_factory() as db:
            await db.execute(
                delete(Membership).where(Membership.organization_id == organization_id)
            )
            await db.execute(delete(Organization).where(Organization.id == organization_id))
            await db.execute(delete(User).where(User.id == founder_user_id))
            await db.commit()


async def test_seed_reuses_a_pre_existing_user_and_never_deletes_it() -> None:
    """A seed email already belongs to a real, unrelated user — created
    before the organization ever existed (e.g. they signed up in another
    org first). seed() must reuse that user row rather than erroring or
    duplicating it, and cleanup must never delete a user it didn't create,
    even though it did have to create a fresh membership for them."""
    session_factory = get_session_factory()
    developer = _SEED_USERS[1]
    assert developer.email == "developer@trinolit.com"

    async with session_factory() as db:
        pre_snapshot = await _snapshot(db)
        assert not pre_snapshot.organization_existed, "test assumes a clean slate"
        assert not pre_snapshot.user_existed[developer.email], "test assumes a clean slate"

        pre_existing_user = User(
            id=uuid7(),
            firebase_uid=f"unrelated-{developer.email}",
            email=developer.email,
            auth_provider=AuthProvider.PASSWORD,
            full_name="Someone Else Entirely",
        )
        db.add(pre_existing_user)
        await db.commit()
        pre_existing_user_id = pre_existing_user.id

    try:
        async with session_factory() as db:
            snapshot = await _snapshot(db)
        assert snapshot.user_existed[developer.email]
        assert not snapshot.organization_existed

        await seed()

        async with session_factory() as db:
            user_result = await db.execute(select(User).where(User.email == developer.email))
            users = user_result.scalars().all()
            assert len(users) == 1, "must reuse, not duplicate, the pre-existing user"
            assert users[0].id == pre_existing_user_id, "must be the same row, not a new one"

        async with session_factory() as db:
            await _cleanup_rows_created_since(db, snapshot)

        async with session_factory() as db:
            # The pre-existing user survives; the organization seed() had to
            # create (and everything else in it) does not.
            assert (
                await db.execute(select(User).where(User.id == pre_existing_user_id))
            ).scalar_one_or_none() is not None
            assert (
                await db.execute(select(Organization).where(Organization.slug == _ORG_SLUG))
            ).scalar_one_or_none() is None
    finally:
        async with session_factory() as db:
            await db.execute(delete(User).where(User.id == pre_existing_user_id))
            await db.commit()

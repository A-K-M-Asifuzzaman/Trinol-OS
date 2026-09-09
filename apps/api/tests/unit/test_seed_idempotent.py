from __future__ import annotations

import uuid
from dataclasses import dataclass, field

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

import trinol.scripts.seed as seed_module
from trinol.core.db.engine import get_session_factory
from trinol.core.ids import uuid7
from trinol.modules.crm.models import Client, Lead
from trinol.modules.identity.models import (
    AuthProvider,
    Membership,
    MembershipStatus,
    Organization,
    User,
)
from trinol.modules.work.models import Project, ProjectMember, Task

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
#
# Codex review (Stage 10, round 2): these tests assumed the real "trinolit"
# org/emails never pre-exist — true in CI's always-fresh DB, but false the
# moment a developer actually runs `make seed` against their persistent
# local Postgres (exactly the workflow ROADMAP.md documents: "make seed"
# then "make check"). `_isolated_seed` below monkeypatches seed.py's own
# module-level constants (`_ORG_SLUG`/`_SEED_USERS`/`_SEED_PROJECTS`) to a
# uniquely-suffixed shadow dataset for the duration of each test, so these
# tests exercise the exact same seed() code path against data that can
# never collide with a real, already-seeded "trinolit" org — reproduced by
# running `make seed` for real, then this suite, both before and after the
# fix, confirming the failure and then its absence.


@pytest.fixture
def _isolated_seed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every seed()-derived identifier this file's tests touch is unique to
    this test run: the org slug, every seed user's email, every project
    code, every client's name, and every lead's email — so a real,
    already-seeded "trinolit" org in the same database (from a developer's
    own `make seed`) can never collide with it."""
    suffix = uuid.uuid4().hex[:8]
    users = tuple(
        seed_module._SeedUser(
            full_name=entry.full_name,
            email=f"seed-test-{suffix}-{entry.full_name.lower()}@trinolit.com",
            role=entry.role,
        )
        for entry in seed_module._SEED_USERS
    )
    email_for = {
        old.email: new.email for old, new in zip(seed_module._SEED_USERS, users, strict=True)
    }
    clients = tuple(
        seed_module._SeedClient(
            name=f"{client.name} {suffix}",
            company=client.company,
            email=client.email,
            phone=client.phone,
            owner_email=email_for[client.owner_email],
            status=client.status,
        )
        for client in seed_module._SEED_CLIENTS
    )
    client_name_for = {
        old.name: new.name for old, new in zip(seed_module._SEED_CLIENTS, clients, strict=True)
    }
    projects = tuple(
        seed_module._SeedProject(
            project_code=f"{project.project_code}-{suffix}",
            name=project.name,
            owner_email=email_for[project.owner_email],
            member_emails=tuple(email_for[email] for email in project.member_emails),
            client_name=(
                client_name_for[project.client_name] if project.client_name is not None else None
            ),
            tasks=tuple(
                seed_module._SeedTask(
                    title=task.title,
                    status=task.status,
                    priority=task.priority,
                    assignee_email=email_for[task.assignee_email],
                )
                for task in project.tasks
            ),
        )
        for project in seed_module._SEED_PROJECTS
    )
    leads = tuple(
        seed_module._SeedLead(
            name=lead.name,
            email=f"seed-test-{suffix}-{lead.email}",
            phone=lead.phone,
            source=lead.source,
            stage=lead.stage,
            assigned_to_email=email_for[lead.assigned_to_email],
            estimated_value=lead.estimated_value,
            next_follow_up=lead.next_follow_up,
            notes=lead.notes,
            lost_reason=lead.lost_reason,
            converted_client_name=(
                client_name_for[lead.converted_client_name]
                if lead.converted_client_name is not None
                else None
            ),
        )
        for lead in seed_module._SEED_LEADS
    )

    monkeypatch.setattr(seed_module, "_ORG_SLUG", f"trinolit-seed-test-{suffix}")
    monkeypatch.setattr(seed_module, "_SEED_USERS", users)
    monkeypatch.setattr(seed_module, "_SEED_CLIENTS", clients)
    monkeypatch.setattr(seed_module, "_SEED_PROJECTS", projects)
    monkeypatch.setattr(seed_module, "_SEED_LEADS", leads)


@dataclass
class _SeedSnapshot:
    organization_existed: bool
    user_existed: dict[str, bool] = field(default_factory=dict)
    membership_existed: dict[str, bool] = field(default_factory=dict)
    project_existed: dict[str, bool] = field(default_factory=dict)
    project_member_existed: dict[tuple[str, str], bool] = field(default_factory=dict)
    task_existed: dict[tuple[str, str], bool] = field(default_factory=dict)
    client_existed: dict[str, bool] = field(default_factory=dict)
    lead_existed: dict[str, bool] = field(default_factory=dict)


async def _snapshot(db: AsyncSession) -> _SeedSnapshot:
    organization = (
        await db.execute(select(Organization).where(Organization.slug == seed_module._ORG_SLUG))
    ).scalar_one_or_none()

    user_existed: dict[str, bool] = {}
    user_ids: dict[str, uuid.UUID] = {}
    for entry in seed_module._SEED_USERS:
        user = (
            await db.execute(select(User).where(User.email == entry.email))
        ).scalar_one_or_none()
        user_existed[entry.email] = user is not None
        if user is not None:
            user_ids[entry.email] = user.id

    membership_existed: dict[str, bool] = {}
    for entry in seed_module._SEED_USERS:
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
    for project_entry in seed_module._SEED_PROJECTS:
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

    client_existed: dict[str, bool] = {}
    for client_entry in seed_module._SEED_CLIENTS:
        client = None
        if organization is not None:
            client = (
                await db.execute(
                    select(Client).where(
                        Client.organization_id == organization.id,
                        Client.name == client_entry.name,
                    )
                )
            ).scalar_one_or_none()
        client_existed[client_entry.name] = client is not None

    lead_existed: dict[str, bool] = {}
    for lead_entry in seed_module._SEED_LEADS:
        lead = None
        if organization is not None:
            lead = (
                await db.execute(
                    select(Lead).where(
                        Lead.organization_id == organization.id, Lead.email == lead_entry.email
                    )
                )
            ).scalar_one_or_none()
        lead_existed[lead_entry.email] = lead is not None

    return _SeedSnapshot(
        organization_existed=organization is not None,
        user_existed=user_existed,
        membership_existed=membership_existed,
        project_existed=project_existed,
        project_member_existed=project_member_existed,
        task_existed=task_existed,
        client_existed=client_existed,
        lead_existed=lead_existed,
    )


async def _cleanup_rows_created_since(db: AsyncSession, snapshot: _SeedSnapshot) -> None:
    """Removes only what didn't exist in `snapshot` — a pre-existing
    organization, user, membership, project, project member, task, client,
    or lead is never touched, regardless of what else this run of seed()
    created alongside it. Tasks and project members are removed before
    their project (FK dependency order), and projects before the
    memberships their owner_id references
    (`fk_projects_org_owner_memberships`) — the exact constraint a naive
    org-then-membership-only cleanup violates. Leads and projects (which
    may reference a client via `converted_client_id`/`client_id`) are
    removed before clients, and clients before memberships (`clients.
    owner_id` references one) — the same class of ordering bug Stage 10
    would otherwise reintroduce for the two new entities."""
    organization = (
        await db.execute(select(Organization).where(Organization.slug == seed_module._ORG_SLUG))
    ).scalar_one_or_none()

    if organization is not None:
        for project_entry in seed_module._SEED_PROJECTS:
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

        for lead_entry in seed_module._SEED_LEADS:
            if snapshot.lead_existed.get(lead_entry.email):
                continue
            await db.execute(
                delete(Lead).where(
                    Lead.organization_id == organization.id, Lead.email == lead_entry.email
                )
            )

        for client_entry in seed_module._SEED_CLIENTS:
            if snapshot.client_existed.get(client_entry.name):
                continue
            await db.execute(
                delete(Client).where(
                    Client.organization_id == organization.id, Client.name == client_entry.name
                )
            )

        for entry in seed_module._SEED_USERS:
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

    for entry in seed_module._SEED_USERS:
        if snapshot.user_existed.get(entry.email):
            continue
        await db.execute(delete(User).where(User.email == entry.email))

    await db.commit()


async def test_seed_is_idempotent(_isolated_seed: None) -> None:
    session_factory = get_session_factory()
    async with session_factory() as db:
        snapshot = await _snapshot(db)

    try:
        await seed_module.seed()
        await seed_module.seed()

        async with session_factory() as db:
            org_result = await db.execute(
                select(Organization).where(Organization.slug == seed_module._ORG_SLUG)
            )
            organizations = org_result.scalars().all()
            assert len(organizations) == 1, "re-running must not duplicate the organization"
            organization = organizations[0]

            membership_result = await db.execute(
                select(Membership).where(Membership.organization_id == organization.id)
            )
            assert len(membership_result.scalars().all()) == len(seed_module._SEED_USERS)

            user_result = await db.execute(
                select(User).where(
                    User.email.in_([entry.email for entry in seed_module._SEED_USERS])
                )
            )
            assert len(user_result.scalars().all()) == len(seed_module._SEED_USERS)

            project_result = await db.execute(
                select(Project).where(Project.organization_id == organization.id)
            )
            projects = {project.project_code: project for project in project_result.scalars()}
            assert set(projects) == {entry.project_code for entry in seed_module._SEED_PROJECTS}, (
                "re-running must not duplicate or lose a project"
            )

            for project_entry in seed_module._SEED_PROJECTS:
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
                if project_entry.client_name is not None:
                    assert project.client_id is not None, (
                        f"{project_entry.project_code}: re-running must keep its client link"
                    )

            client_result = await db.execute(
                select(Client).where(Client.organization_id == organization.id)
            )
            clients_by_name = {client.name: client for client in client_result.scalars()}
            assert set(clients_by_name) == {entry.name for entry in seed_module._SEED_CLIENTS}, (
                "re-running must not duplicate or lose a client"
            )

            lead_result = await db.execute(
                select(Lead).where(Lead.organization_id == organization.id)
            )
            leads_by_email = {lead.email: lead for lead in lead_result.scalars()}
            assert set(leads_by_email) == {entry.email for entry in seed_module._SEED_LEADS}, (
                "re-running must not duplicate or lose a lead"
            )
            for lead_entry in seed_module._SEED_LEADS:
                if lead_entry.converted_client_name is None:
                    continue
                lead = leads_by_email[lead_entry.email]
                expected_client = clients_by_name[lead_entry.converted_client_name]
                assert lead.converted_client_id == expected_client.id, (
                    f"{lead_entry.email}: re-running must keep its converted_client_id"
                )
    finally:
        async with session_factory() as db:
            await _cleanup_rows_created_since(db, snapshot)


async def test_seed_fills_in_missing_users_without_touching_a_pre_existing_org(
    _isolated_seed: None,
) -> None:
    """Partial state: the organization and one seed user/membership already
    exist (as if a previous seed run got that far and stopped); seed() must
    create only what's missing, and cleanup must leave the pre-existing
    organization and membership alone."""
    session_factory = get_session_factory()
    founder = seed_module._SEED_USERS[0]

    async with session_factory() as db:
        pre_snapshot = await _snapshot(db)
        assert not pre_snapshot.organization_existed, "test assumes a clean slate"

        organization = Organization(id=uuid7(), name="TrinolIT", slug=seed_module._ORG_SLUG)
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
            snapshot.user_existed[entry.email]
            for entry in seed_module._SEED_USERS
            if entry is not founder
        )

        await seed_module.seed()

        async with session_factory() as db:
            org_result = await db.execute(
                select(Organization).where(Organization.slug == seed_module._ORG_SLUG)
            )
            assert len(org_result.scalars().all()) == 1, "must reuse, not duplicate, the org"

            user_result = await db.execute(
                select(User).where(
                    User.email.in_([entry.email for entry in seed_module._SEED_USERS])
                )
            )
            assert len(user_result.scalars().all()) == len(seed_module._SEED_USERS)

            membership_result = await db.execute(
                select(Membership).where(Membership.organization_id == organization_id)
            )
            assert len(membership_result.scalars().all()) == len(seed_module._SEED_USERS)

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
            other_emails = [
                entry.email for entry in seed_module._SEED_USERS if entry is not founder
            ]
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


async def test_seed_reuses_a_pre_existing_user_and_never_deletes_it(_isolated_seed: None) -> None:
    """A seed email already belongs to a real, unrelated user — created
    before the organization ever existed (e.g. they signed up in another
    org first). seed() must reuse that user row rather than erroring or
    duplicating it, and cleanup must never delete a user it didn't create,
    even though it did have to create a fresh membership for them."""
    session_factory = get_session_factory()
    developer = seed_module._SEED_USERS[1]

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

        await seed_module.seed()

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
                await db.execute(
                    select(Organization).where(Organization.slug == seed_module._ORG_SLUG)
                )
            ).scalar_one_or_none() is None
    finally:
        async with session_factory() as db:
            await db.execute(delete(User).where(User.id == pre_existing_user_id))
            await db.commit()

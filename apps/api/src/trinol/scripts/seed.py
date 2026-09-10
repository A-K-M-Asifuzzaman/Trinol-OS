"""`make seed` — Phase 1 plan decision 6, extended by Phase 2 decision 4.

One organization (the real company, `trinolit`) with three placeholder
users named after MASTER_PROMPT §36's role hints (Founder/Developer/
Designer) under the real `@trinolit.com` domain. These are structural
placeholders, not real accounts: no Firebase user exists for them yet, so
nobody can actually sign in as one until real accounts are created and their
`firebase_uid` is updated to match. Trivially edited later.

Phase 2 decision 4: two realistic projects — "TrinolIT Website" and an
internal-product project ("Trinol OS" itself, dogfooding), each with a
spread of tasks across every status/priority, enough to exercise the
Kanban board and dashboard tiles realistically.

Phase 3 Stage 10: MASTER_PROMPT §36's clients/leads, now that those
tables exist — 3-5 clients and 10+ leads spread across every `source` and
every `stage` (including one `WON` lead with a real `converted_client_id`
and one `LOST` lead with a `lost_reason`), enough to render real data on
the pipeline board, the clients list, and the dashboard's lead-related
tiles. One of the two Phase 2 seed projects is linked to a seeded client
(`project.client_id`) so the client-detail page's Projects tab isn't
empty either. Invoices still don't exist (Phase 5) — add them here when
that phase lands.

Phase 4 Stage 9: MASTER_PROMPT §36's "past/upcoming meetings" — two past
meetings (one linked to the WEB project/Acme Corp client, with
participants, a decision, and an action item promoted to a real task,
exercising the same MeetingAction -> Task shape `promote_action` itself
produces; one internal, with a decision and an unpromoted action item)
and one upcoming meeting with pending participants, no decisions/actions
yet (a meeting that hasn't happened). `starts_at`/`ends_at` are fixed
absolute datetimes, not computed from "today" — meetings' natural key
(organization, title, starts_at) must stay stable across reruns, unlike
`next_follow_up`'s relative-to-today value above, which is never read
back into an idempotency check. `ponytail: these fixed dates will
eventually stop reading as "past"/"upcoming" as real time moves past
them — cosmetic staleness only, same class of acceptable drift
next_follow_up already has once seeded, not a correctness bug.`

Idempotent: re-running never duplicates a row, matched on the organization's
slug, each user's email, the (organization, user) membership pair, each
project's code, each (project, user) project-member pair, each
(project, title) task pair, each client's name, each lead's email, each
(organization, title, starts_at) meeting, each (meeting, user-or-email)
participant, each (meeting, body) decision, and each (meeting,
description) action.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from trinol.core.authz.permissions import Role
from trinol.core.db.engine import get_session_factory
from trinol.core.db.org_session import register_org_scope_guard
from trinol.core.ids import uuid7
from trinol.modules.crm.models import Client, ClientStatus, Lead, LeadSource, LeadStage
from trinol.modules.identity.models import (
    AuthProvider,
    Membership,
    MembershipStatus,
    Organization,
    User,
)
from trinol.modules.meetings.models import (
    Meeting,
    MeetingAction,
    MeetingDecision,
    MeetingParticipant,
    MeetingParticipantResponse,
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

# Referenced by both _SEED_PROJECTS (project.client_id link) and
# _SEED_CLIENTS/_SEED_LEADS below — a plain constant rather than a forward
# object reference, since _SEED_PROJECTS is defined before _SEED_CLIENTS
# exists.
_ACME_CORP_NAME = "Acme Corp"


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
    # Phase 3 Stage 10: None for a project seeded before clients existed
    # (or a genuinely internal project, like Trinol OS itself) — set for
    # the one project this stage links to a seeded client.
    client_name: str | None = None


_SEED_PROJECTS: tuple[_SeedProject, ...] = (
    _SeedProject(
        project_code="WEB",
        name="TrinolIT Website",
        owner_email=_FOUNDER_EMAIL,
        member_emails=(_DEVELOPER_EMAIL, _DESIGNER_EMAIL),
        client_name=_ACME_CORP_NAME,
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


@dataclass(frozen=True, slots=True)
class _SeedClient:
    name: str
    company: str | None
    email: str | None
    phone: str | None
    owner_email: str
    status: ClientStatus


# MASTER_PROMPT §36: "3-5 clients". _ACME_CORP_NAME is the one
# _SEED_PROJECTS links to and the one the seeded WON lead below converts
# to — a coherent story, not three unrelated facts.
_SEED_CLIENTS: tuple[_SeedClient, ...] = (
    _SeedClient(
        name=_ACME_CORP_NAME,
        company="Acme Corp",
        email="hello@acme.test",
        phone=None,
        owner_email=_FOUNDER_EMAIL,
        status=ClientStatus.ACTIVE,
    ),
    _SeedClient(
        name="Bright Design Studio",
        company=None,
        email="studio@brightdesign.test",
        phone=None,
        owner_email=_DESIGNER_EMAIL,
        status=ClientStatus.ACTIVE,
    ),
    _SeedClient(
        name="Nova Dynamics",
        company="Nova Dynamics LLC",
        email="contact@novadynamics.test",
        phone=None,
        owner_email=_DEVELOPER_EMAIL,
        status=ClientStatus.ACTIVE,
    ),
    _SeedClient(
        name="Legacy Systems Inc",
        company=None,
        email=None,
        phone="+1-555-0100",
        owner_email=_FOUNDER_EMAIL,
        status=ClientStatus.INACTIVE,
    ),
)


@dataclass(frozen=True, slots=True)
class _SeedLead:
    name: str
    email: str
    phone: str | None
    source: LeadSource
    stage: LeadStage
    assigned_to_email: str
    estimated_value: Decimal | None = None
    next_follow_up: date | None = None
    notes: str | None = None
    lost_reason: str | None = None
    # Set only for the one WON lead this stage gives a real
    # converted_client_id (matched against _SEED_CLIENTS by name below) —
    # never for any other stage, mirroring LeadUpdateRequest's own
    # real-world exclusion of this field everywhere else.
    converted_client_name: str | None = None


# MASTER_PROMPT §36: "10+ leads", spread across every LeadSource and every
# LeadStage (both fully covered below, not just "at least one of each" by
# accident) so the pipeline board and dashboard tiles have real, varied
# data to render — not just enough rows to hit a count.
_SEED_LEADS: tuple[_SeedLead, ...] = (
    _SeedLead(
        name="Aiden Cole",
        email="aiden@newlead.test",
        phone=None,
        source=LeadSource.WEBSITE,
        stage=LeadStage.NEW,
        assigned_to_email=_DEVELOPER_EMAIL,
        next_follow_up=date.today() + timedelta(days=3),
    ),
    _SeedLead(
        name="Brianna Foster",
        email="brianna@newlead.test",
        phone=None,
        source=LeadSource.FACEBOOK,
        stage=LeadStage.CONTACTED,
        assigned_to_email=_DESIGNER_EMAIL,
        estimated_value=Decimal("4500.00"),
    ),
    _SeedLead(
        name="Carlos Mendes",
        email="carlos@newlead.test",
        phone=None,
        source=LeadSource.LINKEDIN,
        stage=LeadStage.MEETING,
        assigned_to_email=_FOUNDER_EMAIL,
        estimated_value=Decimal("12000.00"),
        next_follow_up=date.today() - timedelta(days=1),
    ),
    _SeedLead(
        name="Dana Whitfield",
        email="dana@newlead.test",
        phone=None,
        source=LeadSource.REFERRAL,
        stage=LeadStage.PROPOSAL,
        assigned_to_email=_DEVELOPER_EMAIL,
        estimated_value=Decimal("8200.00"),
    ),
    _SeedLead(
        name="Ethan Brooks",
        email="ethan@newlead.test",
        phone=None,
        source=LeadSource.EMAIL,
        stage=LeadStage.NEGOTIATION,
        assigned_to_email=_DESIGNER_EMAIL,
        estimated_value=Decimal("6000.00"),
    ),
    _SeedLead(
        name="Farah Nasser",
        email="farah@newlead.test",
        phone=None,
        source=LeadSource.PHONE,
        stage=LeadStage.WON,
        assigned_to_email=_FOUNDER_EMAIL,
        estimated_value=Decimal("15000.00"),
        converted_client_name=_ACME_CORP_NAME,
    ),
    _SeedLead(
        name="Grace Liu",
        email="grace@newlead.test",
        phone=None,
        source=LeadSource.OTHER,
        stage=LeadStage.LOST,
        assigned_to_email=_FOUNDER_EMAIL,
        lost_reason="Went with a competitor",
    ),
    _SeedLead(
        name="Hassan Ali",
        email="hassan@newlead.test",
        phone=None,
        source=LeadSource.WEBSITE,
        stage=LeadStage.NEGOTIATION,
        assigned_to_email=_DEVELOPER_EMAIL,
        estimated_value=Decimal("9800.00"),
    ),
    _SeedLead(
        name="Isla Thompson",
        email="isla@newlead.test",
        phone=None,
        source=LeadSource.REFERRAL,
        stage=LeadStage.NEW,
        assigned_to_email=_DESIGNER_EMAIL,
        next_follow_up=date.today(),
    ),
    _SeedLead(
        name="Jonah Reyes",
        email="jonah@newlead.test",
        phone="+1-555-0142",
        source=LeadSource.LINKEDIN,
        stage=LeadStage.CONTACTED,
        assigned_to_email=_FOUNDER_EMAIL,
    ),
)


@dataclass(frozen=True, slots=True)
class _SeedMeetingParticipant:
    # Exactly one of these two is set, mirroring
    # ck_meeting_participant_identity (DATABASE.md §3).
    user_email: str | None = None
    external_email: str | None = None
    response: MeetingParticipantResponse = MeetingParticipantResponse.PENDING


@dataclass(frozen=True, slots=True)
class _SeedMeetingDecision:
    body: str
    decided_by_email: str | None = None


@dataclass(frozen=True, slots=True)
class _SeedMeetingAction:
    description: str
    owner_email: str | None = None
    due_date: date | None = None
    # Only the one action this stage exercises promote_action's own shape
    # for sets this. The resulting task's title is always `description`
    # verbatim, matching promote_action's real field mapping exactly
    # (`title = action.description`) — not a separately-authored string,
    # or this wouldn't genuinely exercise the same shape.
    promote: bool = False


@dataclass(frozen=True, slots=True)
class _SeedMeeting:
    title: str
    starts_at: datetime
    ends_at: datetime
    created_by_email: str
    project_code: str | None = None
    client_name: str | None = None
    location: str | None = None
    description: str | None = None
    notes: str | None = None
    participants: tuple[_SeedMeetingParticipant, ...] = ()
    decisions: tuple[_SeedMeetingDecision, ...] = ()
    actions: tuple[_SeedMeetingAction, ...] = ()


# MASTER_PROMPT §36: "past/upcoming meetings". Fixed absolute datetimes —
# see the module docstring for why these can't be computed from "today"
# the way next_follow_up above safely is.
_SEED_MEETINGS: tuple[_SeedMeeting, ...] = (
    _SeedMeeting(
        title="Website Kickoff",
        starts_at=datetime(2026, 8, 3, 15, 0, tzinfo=UTC),
        ends_at=datetime(2026, 8, 3, 16, 0, tzinfo=UTC),
        created_by_email=_FOUNDER_EMAIL,
        project_code="WEB",
        client_name=_ACME_CORP_NAME,
        location="Zoom",
        description="Align on scope and timeline for the website redesign.",
        participants=(
            _SeedMeetingParticipant(
                user_email=_DEVELOPER_EMAIL, response=MeetingParticipantResponse.ACCEPTED
            ),
            _SeedMeetingParticipant(
                user_email=_DESIGNER_EMAIL, response=MeetingParticipantResponse.ACCEPTED
            ),
            _SeedMeetingParticipant(external_email="hello@acme.test"),
        ),
        decisions=(
            _SeedMeetingDecision(
                body="Launch target is end of Q3.", decided_by_email=_FOUNDER_EMAIL
            ),
        ),
        actions=(
            _SeedMeetingAction(
                description="Send the revised proposal to Acme Corp",
                owner_email=_FOUNDER_EMAIL,
                due_date=date(2026, 8, 10),
                promote=True,
            ),
        ),
    ),
    _SeedMeeting(
        title="Sprint Retrospective",
        starts_at=datetime(2026, 8, 20, 17, 0, tzinfo=UTC),
        ends_at=datetime(2026, 8, 20, 17, 30, tzinfo=UTC),
        created_by_email=_DEVELOPER_EMAIL,
        project_code="TOS",
        notes="Went well overall; activity feed took longer than estimated.",
        participants=(
            _SeedMeetingParticipant(
                user_email=_FOUNDER_EMAIL, response=MeetingParticipantResponse.ACCEPTED
            ),
            _SeedMeetingParticipant(
                user_email=_DESIGNER_EMAIL, response=MeetingParticipantResponse.DECLINED
            ),
        ),
        decisions=(
            _SeedMeetingDecision(
                body="Move Kanban board UX to next sprint.", decided_by_email=_DEVELOPER_EMAIL
            ),
        ),
        actions=(
            _SeedMeetingAction(
                description="Re-estimate the activity feed work", owner_email=_DEVELOPER_EMAIL
            ),
        ),
    ),
    _SeedMeeting(
        title="Client Check-in",
        starts_at=datetime(2026, 10, 15, 14, 0, tzinfo=UTC),
        ends_at=datetime(2026, 10, 15, 14, 30, tzinfo=UTC),
        created_by_email=_FOUNDER_EMAIL,
        client_name=_ACME_CORP_NAME,
        location="Zoom",
        participants=(
            _SeedMeetingParticipant(user_email=_DEVELOPER_EMAIL),
            _SeedMeetingParticipant(external_email="hello@acme.test"),
        ),
        # Deliberately no decisions/actions — a meeting that hasn't
        # happened yet.
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
    db: AsyncSession,
    *,
    organization: Organization,
    entry: _SeedProject,
    owner_user_id: uuid.UUID,
    client_id: uuid.UUID | None,
) -> Project:
    result = await db.execute(
        select(Project).where(
            Project.organization_id == organization.id,
            Project.project_code == entry.project_code,
        )
    )
    project = result.scalar_one_or_none()
    if project is not None:
        # Backfill for a project seeded before Stage 10 introduced
        # clients — only ever sets an unset link, never overwrites one a
        # later run's data might disagree with.
        if project.client_id is None and client_id is not None:
            project.client_id = client_id
        return project
    project = Project(
        id=uuid7(),
        organization_id=organization.id,
        project_code=entry.project_code,
        name=entry.name,
        owner_id=owner_user_id,
        client_id=client_id,
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


async def _get_or_create_client(
    db: AsyncSession, *, organization: Organization, entry: _SeedClient, owner_user_id: uuid.UUID
) -> Client:
    result = await db.execute(
        select(Client).where(Client.organization_id == organization.id, Client.name == entry.name)
    )
    client = result.scalar_one_or_none()
    if client is not None:
        return client
    client = Client(
        id=uuid7(),
        organization_id=organization.id,
        name=entry.name,
        company=entry.company,
        email=entry.email,
        phone=entry.phone,
        status=entry.status,
        owner_id=owner_user_id,
    )
    db.add(client)
    await db.flush()
    return client


async def _get_or_create_lead(
    db: AsyncSession,
    *,
    organization: Organization,
    entry: _SeedLead,
    assigned_to_user_id: uuid.UUID,
    converted_client_id: uuid.UUID | None,
) -> Lead:
    result = await db.execute(
        select(Lead).where(Lead.organization_id == organization.id, Lead.email == entry.email)
    )
    lead = result.scalar_one_or_none()
    if lead is not None:
        return lead
    lead = Lead(
        id=uuid7(),
        organization_id=organization.id,
        name=entry.name,
        email=entry.email,
        phone=entry.phone,
        source=entry.source,
        stage=entry.stage,
        assigned_to=assigned_to_user_id,
        estimated_value=entry.estimated_value,
        next_follow_up=entry.next_follow_up,
        notes=entry.notes,
        lost_reason=entry.lost_reason,
        converted_client_id=converted_client_id,
        converted_at=datetime.now(UTC) if converted_client_id is not None else None,
    )
    db.add(lead)
    await db.flush()
    return lead


async def _get_or_create_meeting(
    db: AsyncSession,
    *,
    organization: Organization,
    entry: _SeedMeeting,
    created_by_user_id: uuid.UUID,
    project_id: uuid.UUID | None,
    client_id: uuid.UUID | None,
) -> Meeting:
    result = await db.execute(
        select(Meeting).where(
            Meeting.organization_id == organization.id,
            Meeting.title == entry.title,
            Meeting.starts_at == entry.starts_at,
        )
    )
    meeting = result.scalar_one_or_none()
    if meeting is not None:
        return meeting
    meeting = Meeting(
        id=uuid7(),
        organization_id=organization.id,
        title=entry.title,
        description=entry.description,
        starts_at=entry.starts_at,
        ends_at=entry.ends_at,
        client_id=client_id,
        project_id=project_id,
        location=entry.location,
        notes=entry.notes,
        created_by=created_by_user_id,
    )
    db.add(meeting)
    await db.flush()
    return meeting


async def _ensure_meeting_participant(
    db: AsyncSession,
    *,
    meeting: Meeting,
    entry: _SeedMeetingParticipant,
    user_id: uuid.UUID | None,
) -> None:
    if user_id is not None:
        result = await db.execute(
            select(MeetingParticipant).where(
                MeetingParticipant.organization_id == meeting.organization_id,
                MeetingParticipant.meeting_id == meeting.id,
                MeetingParticipant.user_id == user_id,
            )
        )
    else:
        result = await db.execute(
            select(MeetingParticipant).where(
                MeetingParticipant.organization_id == meeting.organization_id,
                MeetingParticipant.meeting_id == meeting.id,
                MeetingParticipant.external_email == entry.external_email,
            )
        )
    if result.scalar_one_or_none() is not None:
        return
    db.add(
        MeetingParticipant(
            id=uuid7(),
            organization_id=meeting.organization_id,
            meeting_id=meeting.id,
            user_id=user_id,
            external_email=entry.external_email if user_id is None else None,
            response=entry.response,
        )
    )


async def _ensure_meeting_decision(
    db: AsyncSession,
    *,
    meeting: Meeting,
    entry: _SeedMeetingDecision,
    decided_by_user_id: uuid.UUID | None,
) -> None:
    result = await db.execute(
        select(MeetingDecision).where(
            MeetingDecision.organization_id == meeting.organization_id,
            MeetingDecision.meeting_id == meeting.id,
            MeetingDecision.body == entry.body,
        )
    )
    if result.scalar_one_or_none() is not None:
        return
    db.add(
        MeetingDecision(
            id=uuid7(),
            organization_id=meeting.organization_id,
            meeting_id=meeting.id,
            body=entry.body,
            decided_by=decided_by_user_id,
        )
    )


async def _get_or_create_meeting_promoted_task(
    db: AsyncSession,
    *,
    organization: Organization,
    title: str,
    project_id: uuid.UUID | None,
    assignee_id: uuid.UUID | None,
    created_by_user_id: uuid.UUID,
    due_date: date | None,
) -> Task:
    """A standalone task a seeded meeting action promotes to — matched by
    (organization, title) alone, not `_ensure_task`'s (project, title) key,
    since this task isn't necessarily tied to one of `_SEED_PROJECTS`'
    own rows the way every other seeded task is."""
    result = await db.execute(
        select(Task).where(Task.organization_id == organization.id, Task.title == title)
    )
    task = result.scalar_one_or_none()
    if task is not None:
        return task
    task = Task(
        id=uuid7(),
        organization_id=organization.id,
        project_id=project_id,
        title=title,
        assignee_id=assignee_id,
        created_by=created_by_user_id,
        due_date=due_date,
    )
    db.add(task)
    await db.flush()
    return task


async def _get_or_create_meeting_action(
    db: AsyncSession,
    *,
    meeting: Meeting,
    entry: _SeedMeetingAction,
    owner_user_id: uuid.UUID | None,
    task_id: uuid.UUID | None,
) -> MeetingAction:
    result = await db.execute(
        select(MeetingAction).where(
            MeetingAction.organization_id == meeting.organization_id,
            MeetingAction.meeting_id == meeting.id,
            MeetingAction.description == entry.description,
        )
    )
    action = result.scalar_one_or_none()
    if action is not None:
        return action
    action = MeetingAction(
        id=uuid7(),
        organization_id=meeting.organization_id,
        meeting_id=meeting.id,
        description=entry.description,
        owner_id=owner_user_id,
        due_date=entry.due_date,
        task_id=task_id,
    )
    db.add(action)
    await db.flush()
    return action


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

        # Clients before projects/leads: both reference a client by name.
        clients_by_name: dict[str, Client] = {}
        for client_entry in _SEED_CLIENTS:
            owner = users_by_email[client_entry.owner_email]
            clients_by_name[client_entry.name] = await _get_or_create_client(
                db, organization=organization, entry=client_entry, owner_user_id=owner.id
            )

        projects_by_code: dict[str, Project] = {}
        for project_entry in _SEED_PROJECTS:
            owner = users_by_email[project_entry.owner_email]
            client_id = (
                clients_by_name[project_entry.client_name].id
                if project_entry.client_name is not None
                else None
            )
            project = await _get_or_create_project(
                db,
                organization=organization,
                entry=project_entry,
                owner_user_id=owner.id,
                client_id=client_id,
            )
            projects_by_code[project_entry.project_code] = project
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

        for lead_entry in _SEED_LEADS:
            converted_client_id = (
                clients_by_name[lead_entry.converted_client_name].id
                if lead_entry.converted_client_name is not None
                else None
            )
            await _get_or_create_lead(
                db,
                organization=organization,
                entry=lead_entry,
                assigned_to_user_id=users_by_email[lead_entry.assigned_to_email].id,
                converted_client_id=converted_client_id,
            )

        for meeting_entry in _SEED_MEETINGS:
            project_id = (
                projects_by_code[meeting_entry.project_code].id
                if meeting_entry.project_code is not None
                else None
            )
            client_id = (
                clients_by_name[meeting_entry.client_name].id
                if meeting_entry.client_name is not None
                else None
            )
            meeting = await _get_or_create_meeting(
                db,
                organization=organization,
                entry=meeting_entry,
                created_by_user_id=users_by_email[meeting_entry.created_by_email].id,
                project_id=project_id,
                client_id=client_id,
            )
            for participant_entry in meeting_entry.participants:
                user_id = (
                    users_by_email[participant_entry.user_email].id
                    if participant_entry.user_email is not None
                    else None
                )
                await _ensure_meeting_participant(
                    db, meeting=meeting, entry=participant_entry, user_id=user_id
                )
            for decision_entry in meeting_entry.decisions:
                decided_by_user_id = (
                    users_by_email[decision_entry.decided_by_email].id
                    if decision_entry.decided_by_email is not None
                    else None
                )
                await _ensure_meeting_decision(
                    db, meeting=meeting, entry=decision_entry, decided_by_user_id=decided_by_user_id
                )
            for action_entry in meeting_entry.actions:
                owner_user_id = (
                    users_by_email[action_entry.owner_email].id
                    if action_entry.owner_email is not None
                    else None
                )
                task_id = None
                if action_entry.promote:
                    # Exercises the same MeetingAction -> Task shape
                    # promote_action itself produces (ARCHITECTURE.md §3) —
                    # inline construction, not a call into the service
                    # layer, matching every other entity in this script.
                    # title = description verbatim, same field mapping the
                    # real promote_action uses.
                    task = await _get_or_create_meeting_promoted_task(
                        db,
                        organization=organization,
                        title=action_entry.description,
                        project_id=project_id,
                        assignee_id=owner_user_id,
                        created_by_user_id=meeting.created_by,
                        due_date=action_entry.due_date,
                    )
                    task_id = task.id
                await _get_or_create_meeting_action(
                    db,
                    meeting=meeting,
                    entry=action_entry,
                    owner_user_id=owner_user_id,
                    task_id=task_id,
                )
        await db.commit()


def main() -> None:
    asyncio.run(seed())


if __name__ == "__main__":
    main()

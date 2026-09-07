from __future__ import annotations

import uuid
from datetime import date, datetime
from enum import StrEnum

import sqlalchemy as sa
from sqlalchemy import CheckConstraint, ForeignKeyConstraint, Index, UniqueConstraint, text
from sqlalchemy import Enum as PgEnum
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from trinol.core.db.base import Base
from trinol.core.db.org_scoped import OrgScoped
from trinol.core.ids import uuid7

_TZ = sa.DateTime(timezone=True)


class ProjectStatus(StrEnum):
    PLANNING = "PLANNING"
    ACTIVE = "ACTIVE"
    ON_HOLD = "ON_HOLD"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ProjectHealth(StrEnum):
    ON_TRACK = "ON_TRACK"
    AT_RISK = "AT_RISK"
    DELAYED = "DELAYED"


class RoleOnProject(StrEnum):
    """Descriptive only (RBAC.md §3, ROADMAP.md Phase 2 decision 6) — carries
    no permission weight. All authorization here is the organization `Role`
    plus the project-owner resource rule; this enum never gates anything."""

    LEAD = "LEAD"
    CONTRIBUTOR = "CONTRIBUTOR"


class TaskStatus(StrEnum):
    TODO = "TODO"
    IN_PROGRESS = "IN_PROGRESS"
    REVIEW = "REVIEW"
    DONE = "DONE"
    CANCELLED = "CANCELLED"


class TaskPriority(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    URGENT = "URGENT"


class Project(OrgScoped, Base):
    """DATABASE.md §3 (work). `client_id` is omitted until Phase 3 (CRM)
    defines `clients` — nothing to reference yet. `progress` is deliberately
    not a column (ADR-0012): derived on read from task counts."""

    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    project_code: Mapped[str] = mapped_column(sa.Text, nullable=False)
    name: Mapped[str] = mapped_column(sa.Text, nullable=False)
    description: Mapped[str | None] = mapped_column(sa.Text, default=None)
    status: Mapped[ProjectStatus] = mapped_column(
        PgEnum(
            ProjectStatus, name="project_status", values_callable=lambda e: [m.value for m in e]
        ),
        nullable=False,
        server_default=ProjectStatus.PLANNING.value,
    )
    health: Mapped[ProjectHealth] = mapped_column(
        PgEnum(
            ProjectHealth, name="project_health", values_callable=lambda e: [m.value for m in e]
        ),
        nullable=False,
        server_default=ProjectHealth.ON_TRACK.value,
    )
    # Person reference -> memberships, not users (DATABASE.md §5.1).
    # Non-nullable: every project has an owner from creation.
    owner_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    start_date: Mapped[date | None] = mapped_column(sa.Date, default=None)
    deadline: Mapped[date | None] = mapped_column(sa.Date, default=None)
    budget: Mapped[float | None] = mapped_column(sa.Numeric(14, 2), default=None)
    currency: Mapped[str] = mapped_column(sa.Text, nullable=False, server_default="USD")
    repository_url: Mapped[str | None] = mapped_column(sa.Text, default=None)
    production_url: Mapped[str | None] = mapped_column(sa.Text, default=None)
    staging_url: Mapped[str | None] = mapped_column(sa.Text, default=None)
    # Soft delete (ADR-0011): projects are archived, never hard-deleted by a
    # product flow. "Delete project" (RBAC.md §2) sets this, not a SQL DELETE.
    archived_at: Mapped[datetime | None] = mapped_column(_TZ, default=None)
    created_at: Mapped[datetime] = mapped_column(_TZ, server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(_TZ, server_default=text("now()"))

    __table_args__ = (
        UniqueConstraint("organization_id", "project_code", name="uq_project_org_code"),
        # Required by composite FKs from milestones, tasks, project_members,
        # task_comments, task_checklist_items (DATABASE.md §5.1) — redundant
        # for uniqueness (id alone is already unique), required for Postgres
        # to accept those composite FKs. Do not remove as dead weight.
        UniqueConstraint("organization_id", "id", name="uq_projects_org_id"),
        ForeignKeyConstraint(
            ["organization_id", "owner_id"],
            ["memberships.organization_id", "memberships.user_id"],
            name="fk_projects_org_owner_memberships",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "deadline IS NULL OR start_date IS NULL OR deadline >= start_date",
            name="ck_project_dates",
        ),
    )


class ProjectMember(OrgScoped, Base):
    __tablename__ = "project_members"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    project_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    role_on_project: Mapped[RoleOnProject] = mapped_column(
        PgEnum(
            RoleOnProject, name="role_on_project", values_callable=lambda e: [m.value for m in e]
        ),
        nullable=False,
        server_default=RoleOnProject.CONTRIBUTOR.value,
    )
    added_at: Mapped[datetime] = mapped_column(_TZ, server_default=text("now()"))

    __table_args__ = (
        UniqueConstraint("project_id", "user_id", name="uq_project_members_project_user"),
        ForeignKeyConstraint(
            ["organization_id", "project_id"],
            ["projects.organization_id", "projects.id"],
            name="fk_project_members_org_project_projects",
            # A membership row for a project that no longer exists is
            # meaningless (DATABASE.md §5.2's reasoning for
            # project_members.user_id CASCADE, applied identically here).
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["organization_id", "user_id"],
            ["memberships.organization_id", "memberships.user_id"],
            name="fk_project_members_org_user_memberships",
            # DATABASE.md §5.2: "A project membership for a non-member is
            # meaningless."
            ondelete="CASCADE",
        ),
        # uq_project_members_project_user doesn't start with
        # organization_id (unlike memberships/projects/milestones), so this
        # table needs its own explicit index, same as sessions/invitations.
        Index("ix_project_members_organization_id", "organization_id"),
    )


class Milestone(OrgScoped, Base):
    __tablename__ = "milestones"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    project_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    name: Mapped[str] = mapped_column(sa.Text, nullable=False)
    description: Mapped[str | None] = mapped_column(sa.Text, default=None)
    due_date: Mapped[date | None] = mapped_column(sa.Date, default=None)
    completed_at: Mapped[datetime | None] = mapped_column(_TZ, default=None)
    position: Mapped[int] = mapped_column(nullable=False, server_default="0")

    __table_args__ = (
        # Required by tasks.milestone_id's composite FK (DATABASE.md §5.1).
        UniqueConstraint("organization_id", "id", name="uq_milestones_org_id"),
        ForeignKeyConstraint(
            ["organization_id", "project_id"],
            ["projects.organization_id", "projects.id"],
            name="fk_milestones_org_project_projects",
            # Projects are soft-deleted (archived_at), never hard-deleted by
            # a product flow — an unexpected hard delete should fail loudly
            # rather than silently cascade away milestone history.
            ondelete="RESTRICT",
        ),
    )


class Task(OrgScoped, Base):
    """`board_position` is a `numeric` fractional-indexing sort key so a
    Kanban drag reorders one row instead of renumbering a column. `ponytail:
    fractional indexing, rebalance job if precision is ever exhausted.`"""

    __tablename__ = "tasks"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    project_id: Mapped[uuid.UUID | None] = mapped_column(default=None)
    title: Mapped[str] = mapped_column(sa.Text, nullable=False)
    description: Mapped[str | None] = mapped_column(sa.Text, default=None)
    status: Mapped[TaskStatus] = mapped_column(
        PgEnum(TaskStatus, name="task_status", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        server_default=TaskStatus.TODO.value,
    )
    priority: Mapped[TaskPriority] = mapped_column(
        PgEnum(TaskPriority, name="task_priority", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        server_default=TaskPriority.MEDIUM.value,
    )
    # Single assignee, not a join table — ADR-0012 defers TaskAssignee.
    assignee_id: Mapped[uuid.UUID | None] = mapped_column(default=None)
    created_by: Mapped[uuid.UUID] = mapped_column(nullable=False)
    milestone_id: Mapped[uuid.UUID | None] = mapped_column(default=None)
    due_date: Mapped[date | None] = mapped_column(sa.Date, default=None)
    start_date: Mapped[date | None] = mapped_column(sa.Date, default=None)
    estimated_hours: Mapped[float | None] = mapped_column(sa.Numeric(6, 2), default=None)
    actual_hours: Mapped[float | None] = mapped_column(sa.Numeric(6, 2), default=None)
    tags: Mapped[list[str] | None] = mapped_column(ARRAY(sa.Text), default=None)
    board_position: Mapped[float] = mapped_column(sa.Numeric, nullable=False, server_default="0")
    completed_at: Mapped[datetime | None] = mapped_column(_TZ, default=None)
    created_at: Mapped[datetime] = mapped_column(_TZ, server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(_TZ, server_default=text("now()"))

    __table_args__ = (
        # Required by task_comments/task_checklist_items/task_attachments'
        # composite FKs (DATABASE.md §5.1).
        UniqueConstraint("organization_id", "id", name="uq_tasks_org_id"),
        ForeignKeyConstraint(
            ["organization_id", "project_id"],
            ["projects.organization_id", "projects.id"],
            name="fk_tasks_org_project_projects",
            # Nullable (a task may be projectless); projects are
            # soft-deleted only, so an unexpected hard delete should fail
            # loudly rather than silently orphan real deliverable history.
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["organization_id", "milestone_id"],
            ["milestones.organization_id", "milestones.id"],
            name="fk_tasks_org_milestone_milestones",
            # Milestones are a lightweight grouping concept, hard-deleted;
            # a task must survive its milestone disappearing.
            ondelete="SET NULL",
        ),
        ForeignKeyConstraint(
            ["organization_id", "assignee_id"],
            ["memberships.organization_id", "memberships.user_id"],
            name="fk_tasks_org_assignee_memberships",
            # DATABASE.md §5.2: nullable, but SET NULL would silently erase
            # who owned the work — RESTRICT, deactivation is the supported
            # path for removing a person, not deletion.
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["organization_id", "created_by"],
            ["memberships.organization_id", "memberships.user_id"],
            name="fk_tasks_org_created_by_memberships",
            # Non-nullable authorship column (DATABASE.md §5.2): RESTRICT,
            # there is no correct automatic behaviour here.
            ondelete="RESTRICT",
        ),
        Index("ix_tasks_org_status_due", "organization_id", "status", "due_date"),
        Index("ix_tasks_org_assignee_status", "organization_id", "assignee_id", "status"),
        Index("ix_tasks_project", "project_id"),
        CheckConstraint("status <> 'DONE' OR completed_at IS NOT NULL", name="ck_task_completed"),
    )


class TaskComment(OrgScoped, Base):
    __tablename__ = "task_comments"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    task_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    author_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    body: Mapped[str] = mapped_column(sa.Text, nullable=False)
    edited_at: Mapped[datetime | None] = mapped_column(_TZ, default=None)
    created_at: Mapped[datetime] = mapped_column(_TZ, server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(_TZ, server_default=text("now()"))

    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "task_id"],
            ["tasks.organization_id", "tasks.id"],
            name="fk_task_comments_org_task_tasks",
            # ADR-0011: tasks are hard-deleted; a comment without its task
            # is meaningless.
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["organization_id", "author_id"],
            ["memberships.organization_id", "memberships.user_id"],
            name="fk_task_comments_org_author_memberships",
            # Non-nullable authorship column (DATABASE.md §5.2): RESTRICT.
            ondelete="RESTRICT",
        ),
        Index("ix_task_comments_task", "task_id"),
    )


class TaskChecklistItem(OrgScoped, Base):
    __tablename__ = "task_checklist_items"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    task_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    label: Mapped[str] = mapped_column(sa.Text, nullable=False)
    done: Mapped[bool] = mapped_column(nullable=False, server_default=text("false"))
    position: Mapped[int] = mapped_column(nullable=False, server_default="0")

    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "task_id"],
            ["tasks.organization_id", "tasks.id"],
            name="fk_task_checklist_items_org_task_tasks",
            ondelete="CASCADE",
        ),
        Index("ix_task_checklist_items_task", "task_id"),
    )

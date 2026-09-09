from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field, model_validator

from trinol.modules.work.models import ProjectHealth, ProjectStatus, RoleOnProject


class ProjectCreateRequest(BaseModel):
    project_code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    status: ProjectStatus = ProjectStatus.PLANNING
    health: ProjectHealth = ProjectHealth.ON_TRACK
    # Defaults to the actor's own membership if omitted (project_service).
    owner_id: uuid.UUID | None = None
    start_date: date | None = None
    deadline: date | None = None
    budget: Decimal | None = None
    currency: str = Field(default="USD", min_length=3, max_length=3)
    repository_url: str | None = None
    production_url: str | None = None
    staging_url: str | None = None

    @model_validator(mode="after")
    def _dates_consistent(self) -> ProjectCreateRequest:
        # Mirrors ck_project_dates (DATABASE.md §3) — checked here too so a
        # bad request gets a clean 422 instead of a raw DB constraint error.
        if self.deadline is not None and self.start_date is not None:
            if self.deadline < self.start_date:
                raise ValueError("deadline must be on or after start_date")
        return self


class ProjectUpdateRequest(BaseModel):
    """Partial update: only fields present in the request body are applied
    (routes/projects.py uses `model_dump(exclude_unset=True)`). `owner_id`
    is deliberately absent — ownership is set at creation only; transferring
    an existing project's owner isn't requested anywhere in spec and would
    need to reconcile `project_members`, so it's not built until it's a real
    requirement."""

    project_code: str | None = Field(default=None, min_length=1, max_length=64)
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    status: ProjectStatus | None = None
    health: ProjectHealth | None = None
    start_date: date | None = None
    deadline: date | None = None
    budget: Decimal | None = None
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    repository_url: str | None = None
    production_url: str | None = None
    staging_url: str | None = None

    @model_validator(mode="after")
    def _dates_consistent(self) -> ProjectUpdateRequest:
        if self.deadline is not None and self.start_date is not None:
            if self.deadline < self.start_date:
                raise ValueError("deadline must be on or after start_date")
        return self


class ProjectResponse(BaseModel):
    id: uuid.UUID
    project_code: str
    name: str
    description: str | None
    status: ProjectStatus
    health: ProjectHealth
    owner_id: uuid.UUID
    start_date: date | None
    deadline: date | None
    budget: Decimal | None
    currency: str
    repository_url: str | None
    production_url: str | None
    staging_url: str | None
    archived_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ProjectListResponse(BaseModel):
    """ADR-0005: every list endpoint returns {items, total}, never a bare
    array."""

    items: list[ProjectResponse]
    total: int


class ProjectMemberAddRequest(BaseModel):
    # The membership's user_id (matches ProjectMemberResponse.user_id and
    # MembershipResponse.user_id) — not the membership row's own id.
    user_id: uuid.UUID
    role_on_project: RoleOnProject = RoleOnProject.CONTRIBUTOR


class ProjectMemberUpdateRequest(BaseModel):
    role_on_project: RoleOnProject


class ProjectMemberResponse(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    user_id: uuid.UUID
    role_on_project: RoleOnProject
    added_at: datetime


class ProjectMemberListResponse(BaseModel):
    items: list[ProjectMemberResponse]
    total: int

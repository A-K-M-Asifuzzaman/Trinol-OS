from __future__ import annotations

import re
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any

from pydantic import BaseModel, BeforeValidator, Field, WithJsonSchema, model_validator

from trinol.modules.work.models import ProjectHealth, ProjectStatus, RoleOnProject

_BUDGET_PATTERN = r"^-?(?:0|[1-9]\d{0,11})(?:\.\d{1,2})?$"


def _require_budget_decimal_string(value: Any) -> Any:
    if not isinstance(value, str) or re.fullmatch(_BUDGET_PATTERN, value) is None:
        raise ValueError(
            "budget must be a decimal string with at most 12 integer and 2 decimal digits"
        )
    return value


BudgetDecimal = Annotated[
    Decimal,
    BeforeValidator(_require_budget_decimal_string),
    WithJsonSchema({"type": "string", "pattern": _BUDGET_PATTERN}, mode="validation"),
]


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
    budget: BudgetDecimal | None = None
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

    project_code: Annotated[
        str | None,
        WithJsonSchema({"type": "string", "minLength": 1, "maxLength": 64}, mode="validation"),
    ] = Field(default=None, min_length=1, max_length=64)
    name: Annotated[
        str | None,
        WithJsonSchema({"type": "string", "minLength": 1, "maxLength": 200}, mode="validation"),
    ] = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    status: Annotated[
        ProjectStatus | None,
        WithJsonSchema(
            {"type": "string", "enum": [status.value for status in ProjectStatus]},
            mode="validation",
        ),
    ] = None
    health: Annotated[
        ProjectHealth | None,
        WithJsonSchema(
            {"type": "string", "enum": [health.value for health in ProjectHealth]},
            mode="validation",
        ),
    ] = None
    start_date: date | None = None
    deadline: date | None = None
    budget: BudgetDecimal | None = None
    currency: Annotated[
        str | None,
        WithJsonSchema({"type": "string", "minLength": 3, "maxLength": 3}, mode="validation"),
    ] = Field(default=None, min_length=3, max_length=3)
    repository_url: str | None = None
    production_url: str | None = None
    staging_url: str | None = None

    @model_validator(mode="after")
    def _dates_consistent(self) -> ProjectUpdateRequest:
        for field in ("project_code", "name", "status", "health", "currency"):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} may not be null")
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

from __future__ import annotations

import re
import uuid
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from functools import partial
from typing import Annotated, Any

from pydantic import BaseModel, BeforeValidator, Field, WithJsonSchema, model_validator

from trinol.modules.work.models import (
    ProjectHealth,
    ProjectStatus,
    RoleOnProject,
    TaskPriority,
    TaskStatus,
)


def _validate_decimal_string(pattern: str, error: str, value: Any) -> Any:
    """Money/hours fields are `NUMERIC` in Postgres and `Decimal` in Python
    (DATABASE.md §1 / ADR-0007) — accepting a JSON number here would round-
    trip through IEEE-754 float before Pydantic ever sees it, the exact
    thing that rule exists to prevent. A bounded decimal *string* is the
    only representation that can't silently lose precision."""
    if not isinstance(value, str) or re.fullmatch(pattern, value) is None:
        raise ValueError(error)
    return value


# Each alias below must be a literal `Annotated[...]` assignment (not the
# result of a function call) — mypy only recognizes an implicit type alias
# in that exact shape; a factory returning `Any` fails `valid-type` checks
# at every usage site instead. Only the validator logic above is shared.
_BUDGET_PATTERN = r"^-?(?:0|[1-9]\d{0,11})(?:\.\d{1,2})?$"
BudgetDecimal = Annotated[
    Decimal,
    BeforeValidator(
        partial(
            _validate_decimal_string,
            _BUDGET_PATTERN,
            "budget must be a decimal string with at most 12 integer and 2 decimal digits",
        )
    ),
    WithJsonSchema({"type": "string", "pattern": _BUDGET_PATTERN}, mode="validation"),
]

# Numeric(6, 2): at most 4 integer digits. Non-negative — a task can't have
# worked a negative number of hours.
_HOURS_PATTERN = r"^(?:0|[1-9]\d{0,3})(?:\.\d{1,2})?$"
HoursDecimal = Annotated[
    Decimal,
    BeforeValidator(
        partial(
            _validate_decimal_string,
            _HOURS_PATTERN,
            "hours must be a non-negative decimal string with at most 4 integer "
            "and 2 decimal digits",
        )
    ),
    WithJsonSchema({"type": "string", "pattern": _HOURS_PATTERN}, mode="validation"),
]


def _validate_finite_decimal_string(value: Any) -> Any:
    """`board_position` (Stage 4 decision 1) is a plain, unbounded
    `Numeric` — no fixed precision/scale to anchor a digit-count pattern
    like Budget/HoursDecimal above, since fractional indexing can produce
    arbitrarily precise midpoints over many reorders. The one thing that
    must be rejected regardless: Postgres `NUMERIC` has no `Infinity`, and
    a `NaN` would break Kanban column ordering outright — "numeric and
    finite, nothing more" (ROADMAP.md Stage 4 decision)."""
    if not isinstance(value, str):
        raise ValueError("board_position must be a decimal string")
    try:
        parsed = Decimal(value)
    except InvalidOperation:
        raise ValueError("board_position must be a valid decimal string") from None
    if not parsed.is_finite():
        raise ValueError("board_position must be a finite number")
    return value


BoardPositionDecimal = Annotated[
    Decimal,
    BeforeValidator(_validate_finite_decimal_string),
    WithJsonSchema({"type": "string"}, mode="validation"),
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


class MilestoneCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    due_date: date | None = None
    position: int = Field(default=0, ge=0)


class MilestoneResponse(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    description: str | None
    due_date: date | None
    completed_at: datetime | None
    position: int


class MilestoneListResponse(BaseModel):
    items: list[MilestoneResponse]
    total: int


class TaskCreateRequest(BaseModel):
    # Nullable: a task may exist without a project (DATABASE.md §3).
    project_id: uuid.UUID | None = None
    title: str = Field(min_length=1, max_length=300)
    description: str | None = Field(default=None, max_length=8000)
    status: TaskStatus = TaskStatus.TODO
    priority: TaskPriority = TaskPriority.MEDIUM
    # The membership's user_id, like ProjectMemberAddRequest.user_id.
    assignee_id: uuid.UUID | None = None
    milestone_id: uuid.UUID | None = None
    due_date: date | None = None
    start_date: date | None = None
    estimated_hours: HoursDecimal | None = None
    actual_hours: HoursDecimal | None = None
    tags: list[str] | None = Field(default=None, max_length=20)
    # completed_at is deliberately absent: derived from status
    # (task_service sets/clears it), never client-settable — one source of
    # truth for ck_task_completed instead of trusting client-sent dates to
    # agree with the status they're also sending.


class TaskUpdateRequest(BaseModel):
    """Partial update: only fields present in the request body are applied
    (routes/tasks.py uses `model_dump(exclude_unset=True)`). `created_by`
    is absent — authorship is set at creation only, never reassignable."""

    # No WithJsonSchema override here, unlike title/status/priority below:
    # this field genuinely accepts an explicit null (unprojecting a task,
    # like assignee_id/milestone_id) — it isn't in
    # _required_fields_not_null's rejection list, so hiding "null" from the
    # generated schema would misdocument what the API actually accepts.
    project_id: uuid.UUID | None = None
    title: Annotated[
        str | None,
        WithJsonSchema({"type": "string", "minLength": 1, "maxLength": 300}, mode="validation"),
    ] = Field(default=None, min_length=1, max_length=300)
    description: str | None = Field(default=None, max_length=8000)
    status: Annotated[
        TaskStatus | None,
        WithJsonSchema(
            {"type": "string", "enum": [status.value for status in TaskStatus]}, mode="validation"
        ),
    ] = None
    priority: Annotated[
        TaskPriority | None,
        WithJsonSchema(
            {"type": "string", "enum": [priority.value for priority in TaskPriority]},
            mode="validation",
        ),
    ] = None
    assignee_id: uuid.UUID | None = None
    milestone_id: uuid.UUID | None = None
    due_date: date | None = None
    start_date: date | None = None
    estimated_hours: HoursDecimal | None = None
    actual_hours: HoursDecimal | None = None
    tags: list[str] | None = Field(default=None, max_length=20)
    # Stage 4 decision 1: the client computes the midpoint of two neighbors
    # on drag and PATCHes it as an ordinary field — no dedicated reorder
    # endpoint. `ponytail: no server-side collision handling for two
    # simultaneous drags on the same task.`
    board_position: Annotated[
        BoardPositionDecimal | None, WithJsonSchema({"type": "string"}, mode="validation")
    ] = None

    @model_validator(mode="after")
    def _required_fields_not_null(self) -> TaskUpdateRequest:
        # Same reasoning as ProjectUpdateRequest: exclude_unset means a
        # field can be *present* and explicitly null, which would try to
        # null a NOT NULL column — reject that with a clean 422 up front.
        # board_position is NOT NULL too (unlike project_id above), so it
        # belongs in this rejection list, not the null-accepting group.
        for field in ("title", "status", "priority", "board_position"):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} may not be null")
        return self


class TaskResponse(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID | None
    title: str
    description: str | None
    status: TaskStatus
    priority: TaskPriority
    assignee_id: uuid.UUID | None
    created_by: uuid.UUID
    milestone_id: uuid.UUID | None
    due_date: date | None
    start_date: date | None
    estimated_hours: Decimal | None
    actual_hours: Decimal | None
    tags: list[str] | None
    board_position: Decimal
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class TaskListResponse(BaseModel):
    items: list[TaskResponse]
    total: int


class BoardColumn(BaseModel):
    status: TaskStatus
    tasks: list[TaskResponse]


class ProjectBoardResponse(BaseModel):
    """Stage 4 decision 3: unpaginated but capped, not truly unlimited —
    `total` is the real count and `truncated` tells the caller honestly
    whether the 500-task cap actually excluded anything, rather than
    silently returning a partial board with no signal."""

    columns: list[BoardColumn]
    total: int
    truncated: bool


class TaskCommentCreateRequest(BaseModel):
    body: str = Field(min_length=1, max_length=10000)


class TaskCommentUpdateRequest(BaseModel):
    """A comment has exactly one editable field — no exclude_unset partial-
    update ambiguity the way Task/Project updates need."""

    body: str = Field(min_length=1, max_length=10000)


class TaskCommentResponse(BaseModel):
    id: uuid.UUID
    task_id: uuid.UUID
    author_id: uuid.UUID
    body: str
    edited_at: datetime | None
    created_at: datetime
    updated_at: datetime


class TaskCommentListResponse(BaseModel):
    items: list[TaskCommentResponse]
    total: int


class TaskChecklistItemCreateRequest(BaseModel):
    label: str = Field(min_length=1, max_length=500)
    position: int = Field(default=0, ge=0)


class TaskChecklistItemUpdateRequest(BaseModel):
    """Partial update (exclude_unset), same pattern as Task/Project — all
    three columns are NOT NULL, so each rejects an explicit null below."""

    label: Annotated[
        str | None,
        WithJsonSchema({"type": "string", "minLength": 1, "maxLength": 500}, mode="validation"),
    ] = Field(default=None, min_length=1, max_length=500)
    done: Annotated[bool | None, WithJsonSchema({"type": "boolean"}, mode="validation")] = None
    position: Annotated[
        int | None, WithJsonSchema({"type": "integer", "minimum": 0}, mode="validation")
    ] = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _required_fields_not_null(self) -> TaskChecklistItemUpdateRequest:
        for field in ("label", "done", "position"):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} may not be null")
        return self


class TaskChecklistItemResponse(BaseModel):
    id: uuid.UUID
    task_id: uuid.UUID
    label: str
    done: bool
    position: int


class TaskChecklistItemListResponse(BaseModel):
    items: list[TaskChecklistItemResponse]
    total: int


class TaskAttachmentResponse(BaseModel):
    id: uuid.UUID
    task_id: uuid.UUID
    file_id: uuid.UUID
    filename: str
    content_type: str
    size_bytes: int
    uploaded_by: uuid.UUID
    created_at: datetime


class TaskAttachmentListResponse(BaseModel):
    items: list[TaskAttachmentResponse]
    total: int

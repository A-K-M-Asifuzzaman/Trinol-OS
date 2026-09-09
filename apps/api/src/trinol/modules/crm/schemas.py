from __future__ import annotations

import re
import uuid
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from functools import partial
from typing import Annotated, Any

from pydantic import BaseModel, BeforeValidator, Field, WithJsonSchema, model_validator

from trinol.modules.crm.models import ClientStatus, LeadSource, LeadStage


# Decimal-string validation, deliberately duplicated from
# modules/work/schemas.py's BudgetDecimal/BoardPositionDecimal rather than
# imported: ARCHITECTURE.md §3's one-way module dependency rule ("crm must
# not import from work") applies to a plain Python import statement too,
# not just to business-logic calls — small enough to duplicate once rather
# than promote to a shared location for a single second caller.
def _validate_decimal_string(pattern: str, error: str, value: Any) -> Any:
    if not isinstance(value, str) or re.fullmatch(pattern, value) is None:
        raise ValueError(error)
    return value


_ESTIMATED_VALUE_PATTERN = r"^-?(?:0|[1-9]\d{0,11})(?:\.\d{1,2})?$"
LeadValueDecimal = Annotated[
    Decimal,
    BeforeValidator(
        partial(
            _validate_decimal_string,
            _ESTIMATED_VALUE_PATTERN,
            "estimated_value must be a decimal string with at most 12 integer and 2 decimal digits",
        )
    ),
    WithJsonSchema({"type": "string", "pattern": _ESTIMATED_VALUE_PATTERN}, mode="validation"),
]


def _validate_finite_decimal_string(value: Any) -> Any:
    if not isinstance(value, str):
        raise ValueError("board_position must be a decimal string")
    try:
        parsed = Decimal(value)
    except InvalidOperation:
        raise ValueError("board_position must be a valid decimal string") from None
    if not parsed.is_finite():
        raise ValueError("board_position must be a finite number")
    return value


LeadBoardPositionDecimal = Annotated[
    Decimal,
    BeforeValidator(_validate_finite_decimal_string),
    WithJsonSchema({"type": "string"}, mode="validation"),
]


class ClientCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    company: str | None = Field(default=None, max_length=200)
    # Same as identity/schemas.py's InvitationCreateRequest.email — a plain
    # bounded string, no EmailStr (email-validator isn't a dependency here).
    email: str | None = Field(default=None, max_length=320)
    phone: str | None = Field(default=None, max_length=32)
    website: str | None = Field(default=None, max_length=2048)
    address: str | None = Field(default=None, max_length=2000)
    notes: str | None = Field(default=None, max_length=4000)
    status: ClientStatus = ClientStatus.ACTIVE
    # Unlike Project.owner_id, a client isn't required to have one at
    # creation (client_service.create_client) — genuinely optional, no
    # actor-defaulting.
    owner_id: uuid.UUID | None = None


class ClientUpdateRequest(BaseModel):
    """Partial update: only fields present in the request body are applied
    (routes/clients.py uses `model_dump(exclude_unset=True)`)."""

    name: Annotated[
        str | None,
        WithJsonSchema({"type": "string", "minLength": 1, "maxLength": 200}, mode="validation"),
    ] = Field(default=None, min_length=1, max_length=200)
    company: str | None = Field(default=None, max_length=200)
    email: str | None = Field(default=None, max_length=320)
    phone: str | None = Field(default=None, max_length=32)
    website: str | None = Field(default=None, max_length=2048)
    address: str | None = Field(default=None, max_length=2000)
    notes: str | None = Field(default=None, max_length=4000)
    status: Annotated[
        ClientStatus | None,
        WithJsonSchema(
            {"type": "string", "enum": [status.value for status in ClientStatus]},
            mode="validation",
        ),
    ] = None
    owner_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def _not_null(self) -> ClientUpdateRequest:
        for field in ("name", "status"):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} may not be null")
        return self


class ClientResponse(BaseModel):
    id: uuid.UUID
    name: str
    company: str | None
    email: str | None
    phone: str | None
    website: str | None
    address: str | None
    notes: str | None
    status: ClientStatus
    owner_id: uuid.UUID | None
    archived_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ClientListResponse(BaseModel):
    """ADR-0005: every list endpoint returns {items, total}, never a bare
    array."""

    items: list[ClientResponse]
    total: int


class LeadCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    company: str | None = Field(default=None, max_length=200)
    email: str | None = Field(default=None, max_length=320)
    phone: str | None = Field(default=None, max_length=32)
    source: LeadSource
    service: str | None = Field(default=None, max_length=200)
    estimated_value: LeadValueDecimal | None = None
    currency: str = Field(default="USD", min_length=3, max_length=3)
    stage: LeadStage = LeadStage.NEW
    # The membership's user_id, like ProjectMemberAddRequest.user_id.
    assigned_to: uuid.UUID | None = None
    next_follow_up: date | None = None
    notes: str | None = Field(default=None, max_length=4000)

    @model_validator(mode="after")
    def _contact_required(self) -> LeadCreateRequest:
        # Mirrors ck_lead_contact (DATABASE.md §3) — checked here too so a
        # bad request gets a clean 422 instead of a raw DB constraint error.
        if self.email is None and self.phone is None:
            raise ValueError("email or phone is required")
        return self


class LeadUpdateRequest(BaseModel):
    """Partial update: only fields present in the request body are applied
    (routes/leads.py uses `model_dump(exclude_unset=True)`). `stage` and
    `board_position` are ordinary fields here, same as `TaskUpdateRequest`
    allows `status`/`board_position` directly — `update_lead` detects a
    stage change and writes the `lead_stage_events` row itself (DATABASE.md
    §3: "written in the same transaction as the stage change"), the same
    way `update_task` detects a status change and records an activity
    event, rather than needing a separate dedicated route.
    `converted_client_id`/`converted_at` are deliberately absent — set only
    by `work.services.lead_conversion_service.convert_lead`, never
    client-settable, same reasoning `TaskUpdateRequest` excludes
    `completed_at`."""

    name: Annotated[
        str | None,
        WithJsonSchema({"type": "string", "minLength": 1, "maxLength": 200}, mode="validation"),
    ] = Field(default=None, min_length=1, max_length=200)
    company: str | None = Field(default=None, max_length=200)
    email: str | None = Field(default=None, max_length=320)
    phone: str | None = Field(default=None, max_length=32)
    source: Annotated[
        LeadSource | None,
        WithJsonSchema(
            {"type": "string", "enum": [source.value for source in LeadSource]},
            mode="validation",
        ),
    ] = None
    service: str | None = Field(default=None, max_length=200)
    estimated_value: LeadValueDecimal | None = None
    currency: Annotated[
        str | None,
        WithJsonSchema({"type": "string", "minLength": 3, "maxLength": 3}, mode="validation"),
    ] = Field(default=None, min_length=3, max_length=3)
    stage: Annotated[
        LeadStage | None,
        WithJsonSchema(
            {"type": "string", "enum": [stage.value for stage in LeadStage]}, mode="validation"
        ),
    ] = None
    assigned_to: uuid.UUID | None = None
    next_follow_up: date | None = None
    notes: str | None = Field(default=None, max_length=4000)
    lost_reason: str | None = Field(default=None, max_length=2000)
    board_position: Annotated[
        LeadBoardPositionDecimal | None, WithJsonSchema({"type": "string"}, mode="validation")
    ] = None

    @model_validator(mode="after")
    def _not_null(self) -> LeadUpdateRequest:
        for field in ("name", "source", "stage", "currency", "board_position"):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} may not be null")
        # A request touching *both* email and phone in the same body, and
        # nulling both, is the one case this layer can catch on its own —
        # a request that only touches one of the two can't be validated
        # without the row's other current value, so `ck_lead_contact`
        # itself (DATABASE.md §3) is the backstop for that case, translated
        # to a clean error by update_lead's own IntegrityError handling.
        if "email" in self.model_fields_set and "phone" in self.model_fields_set:
            if self.email is None and self.phone is None:
                raise ValueError("email or phone is required")
        return self


class LeadResponse(BaseModel):
    id: uuid.UUID
    name: str
    company: str | None
    email: str | None
    phone: str | None
    source: LeadSource
    service: str | None
    estimated_value: Decimal | None
    currency: str
    stage: LeadStage
    assigned_to: uuid.UUID | None
    next_follow_up: date | None
    notes: str | None
    converted_client_id: uuid.UUID | None
    converted_at: datetime | None
    lost_reason: str | None
    board_position: Decimal
    archived_at: datetime | None
    created_at: datetime
    updated_at: datetime


class LeadListResponse(BaseModel):
    """ADR-0005: every list endpoint returns {items, total}, never a bare
    array."""

    items: list[LeadResponse]
    total: int

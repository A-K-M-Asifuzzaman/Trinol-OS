from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from trinol.core.authz.permissions import Role
from trinol.modules.identity.models import MembershipStatus


class SessionExchangeRequest(BaseModel):
    id_token: str = Field(min_length=1, max_length=4096)


class SessionExchangeResponse(BaseModel):
    user_id: str
    organization_id: str
    role: str


class SessionInfoResponse(BaseModel):
    user_id: str
    organization_id: str
    role: str
    csrf_token: str


class InvitationCreateRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    role: Role


class InvitationResponse(BaseModel):
    id: uuid.UUID
    email: str
    role: Role
    expires_at: datetime
    accepted_at: datetime | None


class InvitationListResponse(BaseModel):
    """ADR-0005: every list endpoint returns {items, total}, never a bare
    array."""

    items: list[InvitationResponse]
    total: int


class InvitationPreviewResponse(BaseModel):
    organization_name: str
    role: Role
    email: str
    expires_at: datetime


class MembershipResponse(BaseModel):
    """MASTER_PROMPT §17's Team page fields, assembled from Membership+User
    by team_service (no ORM relationship joins them)."""

    id: uuid.UUID
    user_id: uuid.UUID
    full_name: str
    email: str
    avatar_url: str | None
    role: Role
    job_title: str | None
    status: MembershipStatus
    joined_at: datetime


class MembershipListResponse(BaseModel):
    items: list[MembershipResponse]
    total: int


class MembershipUpdateRequest(BaseModel):
    role: Role | None = None
    # Only INACTIVE is meaningfully actionable today — it maps to
    # membership_service.remove_member. ON_LEAVE/reactivation has no guarded
    # service behind it yet (technical debt ledger); accepting only this one
    # literal value means asking for anything else is an honest 422, not a
    # silent no-op or an unreviewed new code path.
    status: Literal[MembershipStatus.INACTIVE] | None = None

    @model_validator(mode="after")
    def _at_least_one_field(self) -> MembershipUpdateRequest:
        if self.role is None and self.status is None:
            raise ValueError("At least one of role or status must be provided")
        return self

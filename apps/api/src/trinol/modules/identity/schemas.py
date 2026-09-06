from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from trinol.core.authz.permissions import Role


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

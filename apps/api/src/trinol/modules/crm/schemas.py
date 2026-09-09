from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, Field, WithJsonSchema, model_validator

from trinol.modules.crm.models import ClientStatus


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

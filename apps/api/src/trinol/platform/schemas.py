from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, model_validator

from trinol.platform.models import DocumentKind


class ActivityEventResponse(BaseModel):
    id: uuid.UUID
    event: str
    entity_type: str
    entity_id: uuid.UUID
    actor_id: uuid.UUID | None
    metadata: dict[str, Any]
    created_at: datetime


class ActivityFeedResponse(BaseModel):
    """ADR-0005: every list endpoint returns {items, total}, never a bare
    array."""

    items: list[ActivityEventResponse]
    total: int


class DocumentReferenceCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    url: str = Field(min_length=1, max_length=2000)
    kind: DocumentKind
    project_id: uuid.UUID | None = None
    client_id: uuid.UUID | None = None
    meeting_id: uuid.UUID | None = None


class DocumentReferenceUpdateRequest(BaseModel):
    """Partial update: only fields present in the request body are applied
    (routes/documents.py uses `model_dump(exclude_unset=True)`)."""

    title: str | None = Field(default=None, min_length=1, max_length=200)
    url: str | None = Field(default=None, min_length=1, max_length=2000)
    kind: DocumentKind | None = None
    project_id: uuid.UUID | None = None
    client_id: uuid.UUID | None = None
    meeting_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def _no_null_for_required_fields(self) -> DocumentReferenceUpdateRequest:
        """Same pattern as `IncomeUpdateRequest` (Codex Phase 5 finding):
        `exclude_unset=True` already lets an *omitted* field pass through
        untouched, but an *explicit* `null` for one of `title`/`url`/`kind`
        (all NOT NULL) would otherwise reach the service layer as `None`
        and hit the DB's NOT NULL constraint as an unhandled 500.
        `project_id`/`client_id`/`meeting_id` are genuinely nullable and
        deliberately excluded here."""
        for field in ("title", "url", "kind"):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} may not be null")
        return self


class DocumentReferenceResponse(BaseModel):
    id: uuid.UUID
    title: str
    url: str
    kind: DocumentKind
    project_id: uuid.UUID | None
    client_id: uuid.UUID | None
    meeting_id: uuid.UUID | None
    added_by: uuid.UUID
    created_at: datetime
    updated_at: datetime


class DocumentReferenceListResponse(BaseModel):
    """ADR-0005: every list endpoint returns {items, total}, never a bare
    array."""

    items: list[DocumentReferenceResponse]
    total: int

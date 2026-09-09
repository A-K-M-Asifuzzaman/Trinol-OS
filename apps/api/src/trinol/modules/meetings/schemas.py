from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, Field, WithJsonSchema, model_validator

# Aliased: models.MeetingParticipantResponse is the RSVP-status enum
# (PENDING/ACCEPTED/DECLINED/TENTATIVE); this module's own MeetingParticipant
# Response class below is the API schema for a participant row — same name
# would collide, so the enum is imported under a name that says what it is.
from trinol.modules.meetings.models import (
    MeetingParticipantResponse as ParticipantInviteStatus,
)


class MeetingCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    starts_at: datetime
    ends_at: datetime
    # MASTER_PROMPT.md §14's "related_client"/"related_project" — plain ids,
    # not embedded objects, matching ProjectResponse.client_id/LeadResponse.
    # converted_client_id's existing precedent elsewhere in the codebase.
    client_id: uuid.UUID | None = None
    project_id: uuid.UUID | None = None
    meeting_url: str | None = Field(default=None, max_length=2000)
    location: str | None = Field(default=None, max_length=500)
    notes: str | None = Field(default=None, max_length=4000)

    @model_validator(mode="after")
    def _times_consistent(self) -> MeetingCreateRequest:
        # Mirrors ck_meeting_times (DATABASE.md §3) — checked here too so a
        # bad request gets a clean 422 instead of a raw DB constraint error.
        if self.ends_at <= self.starts_at:
            raise ValueError("ends_at must be after starts_at")
        return self


class MeetingUpdateRequest(BaseModel):
    """Partial update: only fields present in the request body are applied
    (routes/meetings.py uses `model_dump(exclude_unset=True)`). `created_by`
    is absent — authorship is set at creation only, never reassignable."""

    title: Annotated[
        str | None,
        WithJsonSchema({"type": "string", "minLength": 1, "maxLength": 200}, mode="validation"),
    ] = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    client_id: uuid.UUID | None = None
    project_id: uuid.UUID | None = None
    meeting_url: str | None = Field(default=None, max_length=2000)
    location: str | None = Field(default=None, max_length=500)
    notes: str | None = Field(default=None, max_length=4000)

    @model_validator(mode="after")
    def _required_fields_not_null(self) -> MeetingUpdateRequest:
        # Same reasoning as ProjectUpdateRequest/TaskUpdateRequest:
        # exclude_unset means a field can be *present* and explicitly null,
        # which would try to null a NOT NULL column — reject that with a
        # clean 422 up front. Full starts_at/ends_at cross-field consistency
        # (when only one of the two is in this partial update) is checked in
        # the service against the persisted row, same as
        # ProjectUpdateRequest/update_project's start_date/deadline split.
        for field in ("title", "starts_at", "ends_at"):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} may not be null")
        if self.starts_at is not None and self.ends_at is not None:
            if self.ends_at <= self.starts_at:
                raise ValueError("ends_at must be after starts_at")
        return self


class MeetingResponse(BaseModel):
    id: uuid.UUID
    title: str
    description: str | None
    starts_at: datetime
    ends_at: datetime
    client_id: uuid.UUID | None
    project_id: uuid.UUID | None
    meeting_url: str | None
    location: str | None
    notes: str | None
    external_event_id: str | None
    created_by: uuid.UUID
    created_at: datetime
    updated_at: datetime


class MeetingListResponse(BaseModel):
    """ADR-0005: every list endpoint returns {items, total}, never a bare
    array."""

    items: list[MeetingResponse]
    total: int


class MeetingParticipantAddRequest(BaseModel):
    user_id: uuid.UUID | None = None
    external_email: str | None = Field(default=None, max_length=320)

    @model_validator(mode="after")
    def _exactly_one_identity(self) -> MeetingParticipantAddRequest:
        # Mirrors ck_meeting_participant_identity (DATABASE.md §3) — checked
        # here too so a bad request gets a clean 422 instead of a raw DB
        # constraint error.
        if (self.user_id is None) == (self.external_email is None):
            raise ValueError("exactly one of user_id or external_email is required")
        return self


class MeetingParticipantResponseUpdateRequest(BaseModel):
    response: ParticipantInviteStatus


class MeetingParticipantResponse(BaseModel):
    id: uuid.UUID
    meeting_id: uuid.UUID
    user_id: uuid.UUID | None
    external_email: str | None
    response: ParticipantInviteStatus


class MeetingParticipantListResponse(BaseModel):
    items: list[MeetingParticipantResponse]
    total: int

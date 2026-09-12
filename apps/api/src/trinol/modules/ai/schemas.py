from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from trinol.modules.ai.models import KnowledgeSourceType


class ReindexResponse(BaseModel):
    reindexed: int


class SearchResultItem(BaseModel):
    source_type: KnowledgeSourceType
    source_id: uuid.UUID
    content: str


class SearchResponse(BaseModel):
    items: list[SearchResultItem]


class AssistantAskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)


class AssistantAskResponse(BaseModel):
    answer: str
    source_count: int


class LeadScoreResponse(BaseModel):
    id: uuid.UUID
    lead_id: uuid.UUID
    score: int
    rationale: str
    computed_at: datetime
    computed_by: uuid.UUID
    # Not a DB column — computed at read time against the lead's own
    # current updated_at (Phase 8 Stage 5 plan's "staleness check"), so a
    # viewer can tell a cached score might no longer reflect the lead's
    # latest edits without forcing an automatic (and costly) recompute.
    stale: bool


class MeetingSummaryResponse(BaseModel):
    id: uuid.UUID
    meeting_id: uuid.UUID
    content: str
    model: str
    generated_by: uuid.UUID
    created_at: datetime
    updated_at: datetime

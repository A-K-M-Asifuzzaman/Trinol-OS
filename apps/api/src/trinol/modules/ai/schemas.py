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


class MeetingSummaryResponse(BaseModel):
    id: uuid.UUID
    meeting_id: uuid.UUID
    content: str
    model: str
    generated_by: uuid.UUID
    created_at: datetime
    updated_at: datetime

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel


class ReindexResponse(BaseModel):
    reindexed: int


class MeetingSummaryResponse(BaseModel):
    id: uuid.UUID
    meeting_id: uuid.UUID
    content: str
    model: str
    generated_by: uuid.UUID
    created_at: datetime
    updated_at: datetime

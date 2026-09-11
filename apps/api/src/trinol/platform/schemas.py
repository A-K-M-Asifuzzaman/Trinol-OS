from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel


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

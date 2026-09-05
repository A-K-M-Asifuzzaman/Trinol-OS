from __future__ import annotations

from pydantic import BaseModel, Field


class SessionExchangeRequest(BaseModel):
    id_token: str = Field(min_length=1, max_length=4096)


class SessionExchangeResponse(BaseModel):
    user_id: str
    organization_id: str
    role: str

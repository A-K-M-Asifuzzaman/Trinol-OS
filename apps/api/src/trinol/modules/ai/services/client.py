from __future__ import annotations

from typing import Protocol

from fastapi import status

from trinol.core.errors import AppError


class AIClientError(AppError):
    """Raised only when a real AI call is attempted without OPENAI_API_KEY
    configured — never at app boot (same lazy-init posture as
    IdentityVerificationError for a missing FIREBASE_CREDENTIALS)."""

    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    code = "AI_UNAVAILABLE"


class AIClient(Protocol):
    """Phase 8 (ADR-0014). Embedding supports single-query and bounded
    batch calls so reindexing does not serialize provider round trips."""

    async def complete(self, *, system: str, prompt: str) -> str: ...

    async def embed(self, text: str) -> list[float]: ...

    async def embed_many(self, texts: list[str]) -> list[list[float]]: ...

from __future__ import annotations

from typing import Protocol


class AIClientError(Exception):
    """Raised only when a real AI call is attempted without OPENAI_API_KEY
    configured — never at app boot (same lazy-init posture as
    IdentityVerificationError for a missing FIREBASE_CREDENTIALS)."""


class AIClient(Protocol):
    """Phase 8 (ADR-0014). Embedding supports single-query and bounded
    batch calls so reindexing does not serialize provider round trips."""

    async def complete(self, *, system: str, prompt: str) -> str: ...

    async def embed(self, text: str) -> list[float]: ...

    async def embed_many(self, texts: list[str]) -> list[list[float]]: ...

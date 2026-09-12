from __future__ import annotations

from typing import Protocol


class AIClientError(Exception):
    """Raised only when a real AI call is attempted without OPENAI_API_KEY
    configured — never at app boot (same lazy-init posture as
    IdentityVerificationError for a missing FIREBASE_CREDENTIALS)."""


class AIClient(Protocol):
    """Phase 8 (ADR-0014). `embed()` added in Stage 3, once RAG
    infrastructure actually needs it."""

    async def complete(self, *, system: str, prompt: str) -> str: ...

    async def embed(self, text: str) -> list[float]: ...

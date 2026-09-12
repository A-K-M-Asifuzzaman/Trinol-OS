from __future__ import annotations

import hashlib

from trinol.modules.ai.models import EMBEDDING_DIMENSIONS


def _deterministic_vector(text: str, dim: int = EMBEDDING_DIMENSIONS) -> list[float]:
    """Same text -> same vector, different text -> (almost certainly)
    a different one — real embeddings without a real network call, cheap
    enough to run in every test. `reindex_stale`'s own "did this change"
    tests rely on this determinism directly."""
    digest = hashlib.sha256(text.encode()).digest()
    return [(digest[i % len(digest)] / 127.5) - 1.0 for i in range(dim)]


class FakeAIClient:
    """Deterministic test double for `AIClient` (TESTING.md's rule: no test
    anywhere calls a real external provider — same shape as
    `MemoryEmailSender`/`FakeIdentityVerifier`). Records every call so a
    test can assert on prompts/call counts without a real network call.

    `next_response`: an explicit test seam — when set, `complete()` returns
    it verbatim instead of the default templated string (e.g. a test
    proving the 10-suggestion cap needs the fake to actually return more
    than 10 lines)."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.next_response: str | None = None
        self.embed_calls: list[str] = []
        self.embed_batch_calls: list[list[str]] = []
        # Test seam for Stage 4's retrieval-ranking tests: force every
        # embed() call to return the same vector, so similarity ordering
        # is fully deterministic regardless of input text.
        self.next_embedding: list[float] | None = None

    async def complete(self, *, system: str, prompt: str) -> str:
        self.calls.append((system, prompt))
        if self.next_response is not None:
            return self.next_response
        return f"[fake summary of {len(prompt)} chars]"

    async def embed(self, text: str) -> list[float]:
        return (await self.embed_many([text]))[0]

    async def embed_many(self, texts: list[str]) -> list[list[float]]:
        self.embed_batch_calls.append(texts)
        self.embed_calls.extend(texts)
        if self.next_embedding is not None:
            return [self.next_embedding for _ in texts]
        return [_deterministic_vector(text) for text in texts]

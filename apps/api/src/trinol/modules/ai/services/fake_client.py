from __future__ import annotations


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

    async def complete(self, *, system: str, prompt: str) -> str:
        self.calls.append((system, prompt))
        if self.next_response is not None:
            return self.next_response
        return f"[fake summary of {len(prompt)} chars]"

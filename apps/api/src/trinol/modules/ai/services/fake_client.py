from __future__ import annotations


class FakeAIClient:
    """Deterministic test double for `AIClient` (TESTING.md's rule: no test
    anywhere calls a real external provider — same shape as
    `MemoryEmailSender`/`FakeIdentityVerifier`). Records every call so a
    test can assert on prompts/call counts without a real network call."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def complete(self, *, system: str, prompt: str) -> str:
        self.calls.append((system, prompt))
        return f"[fake summary of {len(prompt)} chars]"

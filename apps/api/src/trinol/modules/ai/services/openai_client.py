from __future__ import annotations

from openai import AsyncOpenAI


class OpenAIClient:
    """Phase 8 (ADR-0014): the real `AIClient`, wrapping `openai.AsyncOpenAI`.
    Never constructed in a test — `fake_ai_client` (conftest.py) overrides
    `get_ai_client` for the whole suite (TESTING.md's rule for every
    external dependency, same as EmailSender/IdentityVerifier)."""

    def __init__(self, *, api_key: str, chat_model: str) -> None:
        self._client = AsyncOpenAI(api_key=api_key)
        self._chat_model = chat_model

    async def complete(self, *, system: str, prompt: str) -> str:
        response = await self._client.chat.completions.create(
            model=self._chat_model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
        )
        content = response.choices[0].message.content
        return content or ""

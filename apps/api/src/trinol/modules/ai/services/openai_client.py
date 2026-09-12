from __future__ import annotations

from openai import AsyncOpenAI

from trinol.modules.ai.models import EMBEDDING_DIMENSIONS


class OpenAIClient:
    """Phase 8 (ADR-0014): the real `AIClient`, wrapping `openai.AsyncOpenAI`.
    Never constructed in a test — `fake_ai_client` (conftest.py) overrides
    `get_ai_client` for the whole suite (TESTING.md's rule for every
    external dependency, same as EmailSender/IdentityVerifier)."""

    def __init__(self, *, api_key: str, chat_model: str, embedding_model: str) -> None:
        self._client = AsyncOpenAI(api_key=api_key)
        self._chat_model = chat_model
        self._embedding_model = embedding_model

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

    async def embed(self, text: str) -> list[float]:
        return (await self.embed_many([text]))[0]

    async def embed_many(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        response = await self._client.embeddings.create(
            model=self._embedding_model,
            input=texts,
            dimensions=EMBEDDING_DIMENSIONS,
        )
        return [list(item.embedding) for item in sorted(response.data, key=lambda item: item.index)]

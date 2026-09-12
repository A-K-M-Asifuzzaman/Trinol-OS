from __future__ import annotations

from typing import NoReturn

from trinol.core.deps import get_settings
from trinol.modules.ai.services.client import AIClient, AIClientError
from trinol.modules.ai.services.openai_client import OpenAIClient

_client: AIClient | None = None


class _UnavailableAIClient:
    """Keeps provider availability behind the actual provider operation.

    FastAPI resolves dependencies before the handler, so raising inside
    get_ai_client would bypass resource-level 404 checks even when no AI call
    should occur. This client performs no network work and fails only if a
    service genuinely asks it to generate or embed.
    """

    @staticmethod
    def _raise() -> NoReturn:
        raise AIClientError("AI features are temporarily unavailable.")

    async def complete(self, *, system: str, prompt: str) -> str:
        self._raise()

    async def embed(self, text: str) -> list[float]:
        self._raise()

    async def embed_many(self, texts: list[str]) -> list[list[float]]:
        self._raise()


def get_ai_client() -> AIClient:
    """ADR-0014, mirrors `platform/email/deps.py`'s `get_email_sender`
    exactly: overridden in every test via `app.dependency_overrides` with
    `FakeAIClient` (conftest.py's `fake_ai_client` fixture) — no test
    anywhere in the suite calls the real OpenAI API.

    Lazy init (same posture as `identity/firebase_verifier.py`'s
    `_get_app`): a missing `OPENAI_API_KEY` must not fail app boot. Only an
    actual call to a real AI route without it raises, and only then.
    """
    global _client
    if _client is None:
        settings = get_settings()
        if not settings.openai_api_key:
            _client = _UnavailableAIClient()
        else:
            _client = OpenAIClient(
                api_key=settings.openai_api_key,
                chat_model=settings.openai_chat_model,
                embedding_model=settings.openai_embedding_model,
            )
    return _client

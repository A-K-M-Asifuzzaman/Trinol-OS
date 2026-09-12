from __future__ import annotations

from trinol.core.deps import get_settings
from trinol.modules.ai.services.client import AIClient, AIClientError
from trinol.modules.ai.services.openai_client import OpenAIClient

_client: AIClient | None = None


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
            raise AIClientError("OPENAI_API_KEY is not set; cannot call the AI provider.")
        _client = OpenAIClient(
            api_key=settings.openai_api_key, chat_model=settings.openai_chat_model
        )
    return _client

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from trinol.modules.ai.models import EMBEDDING_DIMENSIONS, KnowledgeSourceType
from trinol.modules.ai.services import deps
from trinol.modules.ai.services.client import AIClientError
from trinol.modules.ai.services.openai_client import OpenAIClient


def test_knowledge_sources_exclude_finance() -> None:
    assert {source.value for source in KnowledgeSourceType} == {
        "MEETING",
        "LEAD",
        "PROJECT",
        "TASK",
    }


@pytest.mark.asyncio
async def test_openai_embeddings_are_batched_and_fixed_to_the_schema_dimension() -> None:
    create = AsyncMock(
        return_value=SimpleNamespace(
            data=[
                SimpleNamespace(index=1, embedding=[2.0]),
                SimpleNamespace(index=0, embedding=[1.0]),
            ]
        )
    )
    client = object.__new__(OpenAIClient)
    client._client = SimpleNamespace(embeddings=SimpleNamespace(create=create))
    client._embedding_model = "test-embedding-model"

    result = await client.embed_many(["first", "second"])

    assert result == [[1.0], [2.0]]
    create.assert_awaited_once_with(
        model="test-embedding-model",
        input=["first", "second"],
        dimensions=EMBEDDING_DIMENSIONS,
    )


@pytest.mark.asyncio
async def test_missing_key_fails_only_when_the_provider_is_used(monkeypatch) -> None:
    monkeypatch.setattr(deps, "_client", None)
    monkeypatch.setattr(
        deps,
        "get_settings",
        lambda: SimpleNamespace(openai_api_key=None),
    )

    client = deps.get_ai_client()

    with pytest.raises(AIClientError, match="temporarily unavailable"):
        await client.embed("test")

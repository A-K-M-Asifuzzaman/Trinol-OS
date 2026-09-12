from __future__ import annotations

from datetime import timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update

from tests.factories import (
    make_lead,
    make_meeting,
    make_project,
)
from tests.helpers import login_as
from trinol.core.authz.permissions import Role
from trinol.modules.ai.models import KnowledgeChunk, KnowledgeSourceType
from trinol.modules.ai.services.embedding_service import reindex_stale

# Phase 8 Stage 3: infrastructure only (embedding + staleness), not the
# permission-aware retrieval filter itself (that's Stage 4's
# retrieval_service, its own dedicated test file).

pytestmark = pytest.mark.usefixtures("db_session")


async def test_reindex_creates_one_chunk_per_seeded_row(
    client: AsyncClient, fake_verifier, fake_ai_client, db_session
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.OWNER)
    meeting = await make_meeting(
        db_session, organization=actor.organization, created_by=actor.membership
    )
    lead = await make_lead(db_session, organization=actor.organization)
    project = await make_project(
        db_session, organization=actor.organization, owner=actor.membership
    )
    await db_session.commit()

    count = await reindex_stale(
        db_session,
        organization_id=actor.organization.id,
        actor=actor.membership,
        ai_client=fake_ai_client,
        max_sources=20,
    )
    assert count == 3

    result = await db_session.execute(
        select(KnowledgeChunk).where(KnowledgeChunk.organization_id == actor.organization.id)
    )
    chunks = {(c.source_type, c.source_id): c for c in result.scalars().all()}
    assert (KnowledgeSourceType.MEETING, meeting.id) in chunks
    assert (KnowledgeSourceType.LEAD, lead.id) in chunks
    assert (KnowledgeSourceType.PROJECT, project.id) in chunks

    meeting_chunk = chunks[(KnowledgeSourceType.MEETING, meeting.id)]
    assert meeting_chunk.source_updated_at == meeting.updated_at
    assert meeting.title in meeting_chunk.content
    assert len(meeting_chunk.embedding) == 1536


async def test_reindex_stale_only_re_embeds_the_row_that_changed(
    client: AsyncClient, fake_verifier, fake_ai_client, db_session
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.OWNER)
    meeting = await make_meeting(
        db_session,
        organization=actor.organization,
        created_by=actor.membership,
        title="Original title",
    )
    lead = await make_lead(db_session, organization=actor.organization)
    await db_session.commit()

    await reindex_stale(
        db_session,
        organization_id=actor.organization.id,
        actor=actor.membership,
        ai_client=fake_ai_client,
    )
    result = await db_session.execute(
        select(KnowledgeChunk).where(KnowledgeChunk.organization_id == actor.organization.id)
    )
    before = {c.source_id: (c.content, c.embedding) for c in result.scalars().all()}

    # Backdate only the meeting's cached chunk (not the meeting itself):
    # Postgres's `now()` (used by trg_meetings_updated_at) is the
    # *transaction* timestamp, frozen for this whole test's one wrapping
    # transaction (TESTING.md's SAVEPOINT-per-test isolation), so a real
    # UPDATE to the meeting can never actually move its own updated_at
    # forward here — and the trigger would stomp any value written to it
    # directly, too. Backdating the cached side of the comparison
    # exercises the exact same "cached_at < source.updated_at" branch
    # without fighting the trigger.
    await db_session.execute(
        update(KnowledgeChunk)
        .where(
            KnowledgeChunk.organization_id == actor.organization.id,
            KnowledgeChunk.source_type == KnowledgeSourceType.MEETING,
            KnowledgeChunk.source_id == meeting.id,
        )
        .values(source_updated_at=meeting.updated_at - timedelta(days=1))
    )
    meeting.title = "Updated title"
    await db_session.commit()

    reindexed_count = await reindex_stale(
        db_session,
        organization_id=actor.organization.id,
        actor=actor.membership,
        ai_client=fake_ai_client,
    )
    assert reindexed_count == 1

    result = await db_session.execute(
        select(KnowledgeChunk).where(KnowledgeChunk.organization_id == actor.organization.id)
    )
    after = {c.source_id: (c.content, c.embedding) for c in result.scalars().all()}

    assert after[meeting.id][0] != before[meeting.id][0]
    assert "Updated title" in after[meeting.id][0]
    assert after[lead.id] == before[lead.id]


async def test_reindex_respects_max_sources_budget(
    client: AsyncClient, fake_verifier, fake_ai_client, db_session
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.OWNER)
    for i in range(5):
        await make_lead(db_session, organization=actor.organization, name=f"Lead {i}")
    await db_session.commit()

    count = await reindex_stale(
        db_session,
        organization_id=actor.organization.id,
        actor=actor.membership,
        ai_client=fake_ai_client,
        max_sources=3,
    )
    assert count == 3

    result = await db_session.execute(
        select(KnowledgeChunk).where(
            KnowledgeChunk.organization_id == actor.organization.id,
            KnowledgeChunk.source_type == KnowledgeSourceType.LEAD,
        )
    )
    assert len(result.scalars().all()) == 3


async def test_reindex_route_requires_admin(
    client: AsyncClient, fake_verifier, fake_ai_client, db_session
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.MANAGER)
    response = await client.post("/api/v1/ai/reindex", headers={"X-CSRF-Token": actor.csrf_token})
    assert response.status_code == 403


async def test_reindex_route_succeeds_for_admin(
    client: AsyncClient, fake_verifier, fake_ai_client, db_session
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.ADMIN)
    await make_lead(db_session, organization=actor.organization)
    await db_session.commit()

    response = await client.post("/api/v1/ai/reindex", headers={"X-CSRF-Token": actor.csrf_token})
    assert response.status_code == 200
    assert response.json()["reindexed"] == 1

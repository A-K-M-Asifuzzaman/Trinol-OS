from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from trinol.core.errors import ForbiddenError, NotFoundError
from trinol.modules.ai.models import KnowledgeChunk, KnowledgeSourceType
from trinol.modules.ai.services.client import AIClient
from trinol.modules.ai.services.embedding_service import ensure_actor_in_org, reindex_stale
from trinol.modules.crm.models import Lead
from trinol.modules.identity.models import Membership
from trinol.modules.meetings.services.meeting_service import (
    ensure_meeting_visible,
    get_meeting_in_org,
)
from trinol.modules.work.models import Task
from trinol.modules.work.services.project_service import ensure_project_visible, get_project_in_org

# ADR-0014: the core permission-safe retrieval mechanism. Never trust the
# chunk row's own metadata — re-fetch the live source entity through its
# owning module's existing visibility rule, every time, for every
# candidate. A chunk whose source was deleted or archived since it was
# indexed is silently dropped, never surfaced.

_OVER_FETCH_MULTIPLIER = 5


async def search_knowledge(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    actor: Membership,
    query: str,
    ai_client: AIClient,
    limit: int = 8,
) -> list[KnowledgeChunk]:
    """Over-fetches candidates by vector distance (pgvector doesn't know
    about permissions, so more are requested than needed), then drops any
    whose source is no longer visible to `actor` — stopping once `limit`
    visible chunks are collected."""
    ensure_actor_in_org(actor, organization_id)
    # Self-healing (Stage 3): keeps the index fresh entirely from this
    # side, bounded, before every search — no write-hooks in the other
    # four modules, no background worker.
    await reindex_stale(db, organization_id=organization_id, actor=actor, ai_client=ai_client)

    query_embedding = await ai_client.embed(query)
    result = await db.execute(
        select(KnowledgeChunk)
        .where(KnowledgeChunk.organization_id == organization_id)
        .order_by(KnowledgeChunk.embedding.cosine_distance(query_embedding))
        .limit(limit * _OVER_FETCH_MULTIPLIER)
    )
    candidates = result.scalars().all()

    visible: list[KnowledgeChunk] = []
    for chunk in candidates:
        if await _is_visible(db, organization_id=organization_id, actor=actor, chunk=chunk):
            visible.append(chunk)
        if len(visible) >= limit:
            break
    return visible


async def _is_visible(
    db: AsyncSession, *, organization_id: uuid.UUID, actor: Membership, chunk: KnowledgeChunk
) -> bool:
    if chunk.source_type == KnowledgeSourceType.MEETING:
        try:
            meeting = await get_meeting_in_org(
                db, organization_id=organization_id, meeting_id=chunk.source_id
            )
        except NotFoundError:
            return False
        try:
            await ensure_meeting_visible(db, meeting=meeting, actor=actor)
        except ForbiddenError:
            return False
        return True

    if chunk.source_type == KnowledgeSourceType.PROJECT:
        try:
            project = await get_project_in_org(
                db, organization_id=organization_id, project_id=chunk.source_id
            )
        except NotFoundError:
            return False
        if project.archived_at is not None:
            return False
        try:
            await ensure_project_visible(db, project=project, actor=actor)
        except ForbiddenError:
            return False
        return True

    if chunk.source_type == KnowledgeSourceType.LEAD:
        # RBAC.md: leads have no ownership-split — org membership (already
        # guaranteed by the organization_id filter above) is the whole
        # visibility rule. Only re-checked for archival/deletion since
        # indexing, not for a permission this project doesn't have.
        row = await db.execute(
            select(Lead.archived_at).where(
                Lead.organization_id == organization_id, Lead.id == chunk.source_id
            )
        )
        matched = row.one_or_none()
        return matched is not None and matched[0] is None

    if chunk.source_type == KnowledgeSourceType.TASK:
        # Same reasoning as LEAD — analytics_service's own docstring
        # documents list_tasks as org-wide transparency, no ownership
        # split. Tasks are hard-deleted (ADR-0011), so existence is the
        # only thing left to re-check.
        row = await db.execute(
            select(Task.id).where(
                Task.organization_id == organization_id, Task.id == chunk.source_id
            )
        )
        return row.scalar_one_or_none() is not None

    # FINANCE is not a valid KnowledgeSourceType (ADR-0014 §0(b)) — if
    # this branch is ever reachable, that's a bug, not a permission gap.
    return False

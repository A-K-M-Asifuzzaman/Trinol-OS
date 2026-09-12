from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from trinol.core.db.org_session import OrgSession
from trinol.core.errors import ForbiddenError
from trinol.core.ids import uuid7
from trinol.modules.ai.models import KnowledgeChunk, KnowledgeSourceType
from trinol.modules.ai.services.client import AIClient
from trinol.modules.crm.models import Lead
from trinol.modules.identity.models import Membership
from trinol.modules.meetings.models import Meeting
from trinol.modules.work.models import Project, Task

# Phase 8 Stage 3 (ADR-0014): no FINANCE branch exists here, and never
# will — KnowledgeSourceType has no such member, so there is no code
# path that could ever embed Income/Expense/Invoice/Payment data.

_DEFAULT_MAX_SOURCES = 20


def ensure_actor_in_org(actor: Membership, organization_id: uuid.UUID) -> None:
    """Defense in depth, same reasoning as every other module's own copy
    of this check (e.g. meetings.services.meeting_service.
    ensure_actor_in_org) — the ai module's own copy, reused by every
    service under it."""
    if actor.organization_id != organization_id:
        raise ForbiddenError("Actor does not belong to this organization")


@dataclass(frozen=True, slots=True)
class _Candidate:
    source_type: KnowledgeSourceType
    source_id: uuid.UUID
    source_updated_at: datetime
    content: str


def _meeting_content(title: str, description: str | None, notes: str | None) -> str:
    parts = [f"Meeting: {title}"]
    if description:
        parts.append(f"Description: {description}")
    if notes:
        parts.append(f"Notes: {notes}")
    return "\n".join(parts)


def _lead_content(
    name: str, company: str | None, stage: str, source: str, notes: str | None
) -> str:
    parts = [f"Lead: {name}", f"Stage: {stage}", f"Source: {source}"]
    if company:
        parts.append(f"Company: {company}")
    if notes:
        parts.append(f"Notes: {notes}")
    return "\n".join(parts)


def _project_content(name: str, description: str | None) -> str:
    parts = [f"Project: {name}"]
    if description:
        parts.append(f"Description: {description}")
    return "\n".join(parts)


def _task_content(title: str, description: str | None) -> str:
    parts = [f"Task: {title}"]
    if description:
        parts.append(f"Description: {description}")
    return "\n".join(parts)


async def _cached_updated_at(
    db: AsyncSession, *, organization_id: uuid.UUID, source_type: KnowledgeSourceType
) -> dict[uuid.UUID, datetime]:
    result = await db.execute(
        select(KnowledgeChunk.source_id, KnowledgeChunk.source_updated_at).where(
            KnowledgeChunk.organization_id == organization_id,
            KnowledgeChunk.source_type == source_type,
        )
    )
    return {row[0]: row[1] for row in result.all()}


def _stale(
    rows: list[tuple[uuid.UUID, datetime, str]],
    *,
    source_type: KnowledgeSourceType,
    cached: dict[uuid.UUID, datetime],
    budget: int,
) -> list[_Candidate]:
    stale: list[_Candidate] = []
    for source_id, updated_at, content in rows:
        cached_at = cached.get(source_id)
        if cached_at is None or cached_at < updated_at:
            stale.append(
                _Candidate(
                    source_type=source_type,
                    source_id=source_id,
                    source_updated_at=updated_at,
                    content=content,
                )
            )
            if len(stale) >= budget:
                break
    return stale


async def _stale_meetings(
    db: AsyncSession, *, organization_id: uuid.UUID, budget: int
) -> list[_Candidate]:
    if budget <= 0:
        return []
    result = await db.execute(
        select(Meeting.id, Meeting.updated_at, Meeting.title, Meeting.description, Meeting.notes)
        .where(Meeting.organization_id == organization_id)
        .order_by(Meeting.updated_at.desc())
    )
    rows = [
        (id_, updated_at, _meeting_content(title, description, notes))
        for id_, updated_at, title, description, notes in result.all()
    ]
    cached = await _cached_updated_at(
        db, organization_id=organization_id, source_type=KnowledgeSourceType.MEETING
    )
    return _stale(rows, source_type=KnowledgeSourceType.MEETING, cached=cached, budget=budget)


async def _stale_leads(
    db: AsyncSession, *, organization_id: uuid.UUID, budget: int
) -> list[_Candidate]:
    if budget <= 0:
        return []
    result = await db.execute(
        select(
            Lead.id, Lead.updated_at, Lead.name, Lead.company, Lead.stage, Lead.source, Lead.notes
        )
        .where(Lead.organization_id == organization_id, Lead.archived_at.is_(None))
        .order_by(Lead.updated_at.desc())
    )
    rows = [
        (id_, updated_at, _lead_content(name, company, stage.value, source.value, notes))
        for id_, updated_at, name, company, stage, source, notes in result.all()
    ]
    cached = await _cached_updated_at(
        db, organization_id=organization_id, source_type=KnowledgeSourceType.LEAD
    )
    return _stale(rows, source_type=KnowledgeSourceType.LEAD, cached=cached, budget=budget)


async def _stale_projects(
    db: AsyncSession, *, organization_id: uuid.UUID, budget: int
) -> list[_Candidate]:
    if budget <= 0:
        return []
    result = await db.execute(
        select(Project.id, Project.updated_at, Project.name, Project.description)
        .where(Project.organization_id == organization_id, Project.archived_at.is_(None))
        .order_by(Project.updated_at.desc())
    )
    rows = [
        (id_, updated_at, _project_content(name, description))
        for id_, updated_at, name, description in result.all()
    ]
    cached = await _cached_updated_at(
        db, organization_id=organization_id, source_type=KnowledgeSourceType.PROJECT
    )
    return _stale(rows, source_type=KnowledgeSourceType.PROJECT, cached=cached, budget=budget)


async def _stale_tasks(
    db: AsyncSession, *, organization_id: uuid.UUID, budget: int
) -> list[_Candidate]:
    if budget <= 0:
        return []
    result = await db.execute(
        select(Task.id, Task.updated_at, Task.title, Task.description)
        .where(Task.organization_id == organization_id)
        .order_by(Task.updated_at.desc())
    )
    rows = [
        (id_, updated_at, _task_content(title, description))
        for id_, updated_at, title, description in result.all()
    ]
    cached = await _cached_updated_at(
        db, organization_id=organization_id, source_type=KnowledgeSourceType.TASK
    )
    return _stale(rows, source_type=KnowledgeSourceType.TASK, cached=cached, budget=budget)


async def chunk_and_embed(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    ai_client: AIClient,
    candidates: list[_Candidate],
) -> int:
    """Upserts one `KnowledgeChunk` (chunk_index=0) per candidate — embeds,
    then replaces the existing row's content/embedding/source_updated_at
    if one exists, else inserts a new one. One commit for the whole batch."""
    if not candidates:
        return 0

    org_session = OrgSession(db, organization_id=organization_id)
    for candidate in candidates:
        embedding = await ai_client.embed(candidate.content)
        result = await db.execute(
            org_session.select(KnowledgeChunk).where(
                KnowledgeChunk.source_type == candidate.source_type,
                KnowledgeChunk.source_id == candidate.source_id,
                KnowledgeChunk.chunk_index == 0,
            )
        )
        chunk = result.scalar_one_or_none()
        if chunk is None:
            chunk = KnowledgeChunk(
                id=uuid7(),
                source_type=candidate.source_type,
                source_id=candidate.source_id,
                source_updated_at=candidate.source_updated_at,
                chunk_index=0,
                content=candidate.content,
                embedding=embedding,
            )
            org_session.add(chunk)
        else:
            chunk.source_updated_at = candidate.source_updated_at
            chunk.content = candidate.content
            chunk.embedding = embedding

    await db.commit()
    return len(candidates)


async def reindex_stale(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    actor: Membership,
    ai_client: AIClient,
    max_sources: int = _DEFAULT_MAX_SOURCES,
) -> int:
    """Finds rows across all four source types with no chunk yet, or whose
    own `updated_at` is newer than the cached chunk's, embeds just those
    (capped at `max_sources` total across all types), and upserts them.

    Deliberately bounded and synchronous (ADR-0014/ADR-0010): this keeps
    the index eventually-fresh entirely from the `ai` side, with no write-
    hooks threaded through meetings/crm/work, and no background worker."""
    ensure_actor_in_org(actor, organization_id)
    candidates: list[_Candidate] = []
    candidates += await _stale_meetings(
        db, organization_id=organization_id, budget=max_sources - len(candidates)
    )
    candidates += await _stale_leads(
        db, organization_id=organization_id, budget=max_sources - len(candidates)
    )
    candidates += await _stale_projects(
        db, organization_id=organization_id, budget=max_sources - len(candidates)
    )
    candidates += await _stale_tasks(
        db, organization_id=organization_id, budget=max_sources - len(candidates)
    )
    return await chunk_and_embed(
        db, organization_id=organization_id, ai_client=ai_client, candidates=candidates
    )

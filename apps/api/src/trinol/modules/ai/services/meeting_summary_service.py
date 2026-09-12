from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from trinol.core.db.org_session import OrgSession
from trinol.core.deps import get_settings
from trinol.core.errors import ForbiddenError, NotFoundError
from trinol.core.ids import uuid7
from trinol.modules.ai.models import MeetingSummary
from trinol.modules.ai.services.client import AIClient
from trinol.modules.identity.models import Membership
from trinol.modules.meetings.services.meeting_service import (
    can_write_meeting,
    ensure_actor_in_org,
    ensure_meeting_visible,
    get_meeting_in_org,
)
from trinol.platform.activity import record

_SYSTEM_PROMPT = (
    "You summarize internal company meeting notes for the team that attended. "
    "Write a short, factual summary (3-6 sentences) of what was discussed and "
    "decided. Only use the notes given to you. Never invent attendees, dates, "
    "or figures that are not in the notes."
)


def _build_prompt(*, title: str, description: str | None, notes: str | None) -> str:
    parts = [f"Meeting title: {title}"]
    if description:
        parts.append(f"Description: {description}")
    parts.append(f"Notes:\n{notes or '(no notes recorded)'}")
    return "\n\n".join(parts)


async def _get_summary_row(
    db: AsyncSession, *, organization_id: uuid.UUID, meeting_id: uuid.UUID
) -> MeetingSummary | None:
    org_session = OrgSession(db, organization_id=organization_id)
    result = await db.execute(
        org_session.select(MeetingSummary).where(MeetingSummary.meeting_id == meeting_id)
    )
    return result.scalar_one_or_none()


async def summarize_meeting(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    actor: Membership,
    meeting_id: uuid.UUID,
    ai_client: AIClient,
) -> MeetingSummary:
    """Regenerates in place (no history — same shape every later Phase 8
    "current state only" table uses). Reuses `meeting_service`'s own edit
    rule: same actors who may edit a meeting may (re)summarize it — this
    isn't a separate capability, MEETING_WRITE_OWN already covers it."""
    ensure_actor_in_org(actor, organization_id)
    meeting = await get_meeting_in_org(db, organization_id=organization_id, meeting_id=meeting_id)
    if not can_write_meeting(actor, meeting):
        raise ForbiddenError("Insufficient permission to summarize this meeting")

    prompt = _build_prompt(
        title=meeting.title, description=meeting.description, notes=meeting.notes
    )
    content = await ai_client.complete(system=_SYSTEM_PROMPT, prompt=prompt)
    model = get_settings().openai_chat_model

    summary = await _get_summary_row(db, organization_id=organization_id, meeting_id=meeting_id)
    if summary is None:
        org_session = OrgSession(db, organization_id=organization_id)
        summary = MeetingSummary(
            id=uuid7(),
            meeting_id=meeting_id,
            content=content,
            model=model,
            generated_by=actor.user_id,
        )
        org_session.add(summary)
    else:
        summary.content = content
        summary.model = model
        summary.generated_by = actor.user_id

    await record(
        db,
        organization_id=organization_id,
        event="meeting_summary.generated",
        entity_type="meeting",
        entity_id=meeting_id,
        actor_id=actor.user_id,
        metadata={},
    )
    await db.commit()
    return summary


async def get_meeting_summary(
    db: AsyncSession, *, organization_id: uuid.UUID, actor: Membership, meeting_id: uuid.UUID
) -> MeetingSummary:
    ensure_actor_in_org(actor, organization_id)
    meeting = await get_meeting_in_org(db, organization_id=organization_id, meeting_id=meeting_id)
    await ensure_meeting_visible(db, meeting=meeting, actor=actor)

    summary = await _get_summary_row(db, organization_id=organization_id, meeting_id=meeting_id)
    if summary is None:
        raise NotFoundError("This meeting has not been summarized yet")
    return summary

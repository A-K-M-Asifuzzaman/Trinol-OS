from __future__ import annotations

import re
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from trinol.core.db.org_session import OrgSession
from trinol.core.errors import ForbiddenError
from trinol.core.ids import uuid7
from trinol.modules.ai.services.client import AIClient
from trinol.modules.identity.models import Membership
from trinol.modules.meetings.models import MeetingAction, MeetingActionSource
from trinol.modules.meetings.services.meeting_service import (
    can_write_meeting,
    ensure_actor_in_org,
    get_meeting_in_org,
)
from trinol.platform.activity import record

# Phase 8 Stage 2 plan §0(c): this lives in ai.services, not meetings.
# services, even though it writes MeetingAction rows — the established
# direction is ai -> meetings (not the reverse), so the cross-module
# transaction belongs on the importing (ai) side, inline-constructing the
# row directly (never via meetings' own create_action, which
# auto-commits and would break atomicity) — the same shape work.services.
# convert_lead and meetings.services.promote_action already use for their
# own cross-module writes, just with the module roles reversed because the
# dependency arrow itself is reversed here.

_MAX_SUGGESTIONS = 10

_SYSTEM_PROMPT = (
    "You extract concrete action items from internal company meeting notes. "
    "Read the notes and list each distinct action item on its own line, with "
    "no numbering, bullets, or extra commentary — just the action text. Only "
    "use what is in the notes. If there are no clear action items, respond "
    "with nothing."
)

_LEADING_MARKER_RE = re.compile(r"^(?:[-*•]|\d+[.)])\s*")


def _build_prompt(*, title: str, description: str | None, notes: str | None) -> str:
    parts = [f"Meeting title: {title}"]
    if description:
        parts.append(f"Description: {description}")
    parts.append(f"Notes:\n{notes or '(no notes recorded)'}")
    return "\n\n".join(parts)


def _parse_action_lines(raw: str) -> list[str]:
    """Line-based, not JSON: far more robust to real model output variance
    than asking for and parsing structured JSON, and just as easy to cap.
    Strips a leading bullet/number marker per line; blank lines dropped."""
    lines: list[str] = []
    for line in raw.splitlines():
        cleaned = _LEADING_MARKER_RE.sub("", line.strip()).strip()
        if cleaned:
            lines.append(cleaned)
    return lines[:_MAX_SUGGESTIONS]


async def extract_actions(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    actor: Membership,
    meeting_id: uuid.UUID,
    ai_client: AIClient,
) -> list[MeetingAction]:
    """Reuses meeting_service's own edit rule (creator or MANAGER+) — same
    capability tier as summarize_meeting, not a separate permission.
    Capped at 10 suggestions per call regardless of how many lines the
    model returns. No owner/due_date is guessed — a human reviews/edits/
    deletes the suggestions through the existing action UI, same as any
    other action item."""
    ensure_actor_in_org(actor, organization_id)
    meeting = await get_meeting_in_org(db, organization_id=organization_id, meeting_id=meeting_id)
    if not can_write_meeting(actor, meeting):
        raise ForbiddenError("Insufficient permission to extract actions for this meeting")

    prompt = _build_prompt(
        title=meeting.title, description=meeting.description, notes=meeting.notes
    )
    raw = await ai_client.complete(system=_SYSTEM_PROMPT, prompt=prompt)
    descriptions = _parse_action_lines(raw)

    org_session = OrgSession(db, organization_id=organization_id)
    created: list[MeetingAction] = []
    for description in descriptions:
        action = MeetingAction(
            id=uuid7(),
            meeting_id=meeting_id,
            description=description,
            source=MeetingActionSource.AI,
        )
        org_session.add(action)
        created.append(action)

    if created:
        await record(
            db,
            organization_id=organization_id,
            event="meeting_action.ai_extracted",
            entity_type="meeting",
            entity_id=meeting_id,
            actor_id=actor.user_id,
            metadata={"count": len(created)},
        )
    await db.commit()
    return created

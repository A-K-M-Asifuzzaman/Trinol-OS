from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from trinol.core.db.org_session import OrgSession
from trinol.core.errors import NotFoundError
from trinol.core.ids import uuid7
from trinol.modules.ai.models import LeadScore
from trinol.modules.ai.services.client import AIClient
from trinol.modules.ai.services.embedding_service import ensure_actor_in_org
from trinol.modules.crm.models import Lead
from trinol.modules.crm.services.lead_service import get_lead_in_org
from trinol.modules.identity.models import Membership

_SYSTEM_PROMPT = (
    "You score how likely an internal company lead is to convert into a "
    "paying client, on a scale from 0 (very unlikely) to 100 (very "
    "likely). Consider the lead's stage, source, estimated value, and "
    "notes. Respond with the integer score alone on the first line, "
    "followed by a short one-paragraph rationale. Only use the "
    "information given -- never invent details not present."
)

_SCORE_LINE_RE = re.compile(r"-?\d+")

_MIN_SCORE = 0
_MAX_SCORE = 100


def _build_prompt(lead: Lead) -> str:
    parts = [
        f"Lead: {lead.name}",
        f"Stage: {lead.stage.value}",
        f"Source: {lead.source.value}",
    ]
    if lead.company:
        parts.append(f"Company: {lead.company}")
    if lead.estimated_value is not None:
        parts.append(f"Estimated value: {lead.estimated_value} {lead.currency}")
    if lead.notes:
        parts.append(f"Notes: {lead.notes}")
    return "\n".join(parts)


def _parse_score_and_rationale(raw: str) -> tuple[int, str]:
    """Line-based, same reasoning as action_extraction_service's own
    parsing — the score is the first line, everything else is rationale.
    Never trusts the model's own arithmetic to stay in [0, 100]."""
    lines = raw.strip().splitlines()
    first_line = lines[0] if lines else ""
    match = _SCORE_LINE_RE.search(first_line)
    raw_score = int(match.group()) if match else 0
    score = max(_MIN_SCORE, min(_MAX_SCORE, raw_score))
    rationale = "\n".join(lines[1:]).strip() or raw.strip()
    return score, rationale


async def _get_score_row(
    db: AsyncSession, *, organization_id: uuid.UUID, lead_id: uuid.UUID
) -> LeadScore | None:
    org_session = OrgSession(db, organization_id=organization_id)
    result = await db.execute(org_session.select(LeadScore).where(LeadScore.lead_id == lead_id))
    return result.scalar_one_or_none()


async def score_lead(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    actor: Membership,
    lead_id: uuid.UUID,
    ai_client: AIClient,
) -> LeadScore:
    """Regenerates in place — reuses `LEAD_WRITE`'s existing MANAGER+
    tier (leads have no ownership-split, RBAC.md), so no further
    per-row check is needed beyond the route's own `require(Permission.
    LEAD_WRITE)`."""
    ensure_actor_in_org(actor, organization_id)
    lead = await get_lead_in_org(db, organization_id=organization_id, lead_id=lead_id)

    prompt = _build_prompt(lead)
    raw = await ai_client.complete(system=_SYSTEM_PROMPT, prompt=prompt)
    score, rationale = _parse_score_and_rationale(raw)
    now = datetime.now(UTC)

    statement = insert(LeadScore).values(
        id=uuid7(),
        organization_id=organization_id,
        lead_id=lead_id,
        score=score,
        rationale=rationale,
        computed_at=now,
        computed_by=actor.user_id,
    )
    result = await db.execute(
        statement.on_conflict_do_update(
            constraint="uq_lead_scores_org_lead",
            set_={
                "score": statement.excluded.score,
                "rationale": statement.excluded.rationale,
                "computed_at": statement.excluded.computed_at,
                "computed_by": statement.excluded.computed_by,
            },
        ).returning(LeadScore)
    )
    existing = result.scalar_one()

    await db.commit()
    return existing


async def get_lead_score(
    db: AsyncSession, *, organization_id: uuid.UUID, actor: Membership, lead_id: uuid.UUID
) -> tuple[LeadScore, bool]:
    """Reuses `LEAD_READ`'s existing org-wide, no-ownership-split rule.
    Returns `(score, stale)` — `stale` is true when the lead has been
    edited since this score was last computed, so a viewer can tell a
    cached score might be out of date without forcing an automatic (and
    costly) recompute on every read."""
    ensure_actor_in_org(actor, organization_id)
    lead = await get_lead_in_org(db, organization_id=organization_id, lead_id=lead_id)
    score = await _get_score_row(db, organization_id=organization_id, lead_id=lead_id)
    if score is None:
        raise NotFoundError("This lead has not been scored yet")
    stale = lead.updated_at > score.computed_at
    return score, stale

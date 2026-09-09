from __future__ import annotations

import re
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from trinol.core.authz.permissions import Role
from trinol.core.db.org_session import OrgSession
from trinol.core.errors import ConflictError, ForbiddenError
from trinol.core.ids import uuid7
from trinol.modules.crm.models import Client, ClientStatus, Lead, LeadStage
from trinol.modules.crm.services.lead_service import (
    change_lead_stage,
    ensure_actor_in_org,
    get_lead_in_org,
)
from trinol.modules.identity.models import Membership
from trinol.modules.work.models import (
    Project,
    ProjectHealth,
    ProjectMember,
    ProjectStatus,
    RoleOnProject,
)
from trinol.platform.activity import record

# ARCHITECTURE.md §3: "crm must not import from work" — the reverse
# direction (work -> crm) is the one explicitly allowed one, which is why
# this cross-module transaction lives here rather than in modules/crm.

_MANAGER_UP = (Role.MANAGER, Role.ADMIN, Role.OWNER)
_PROJECT_CODE_CONSTRAINT = "uq_project_org_code"


@dataclass(frozen=True, slots=True)
class LeadConversion:
    lead: Lead
    client: Client
    project: Project


def _violates_constraint(exc: IntegrityError, name: str) -> bool:
    current: BaseException | None = exc
    while current is not None:
        if getattr(current, "constraint_name", None) == name:
            return True
        current = current.__cause__
    return False


def _project_code_from_lead(lead: Lead) -> str:
    # ponytail: no shared project-code generator exists anywhere in the
    # codebase (create_project always takes a client-supplied code) — a
    # short name slug plus a random suffix is unique enough in practice
    # that a real collision surfaces as a 409 instead of needing a retry
    # loop; add one if this ever actually fires.
    #
    # secrets.token_hex, not uuid7().hex[:6]: found while building Stage 6's
    # own reference-number generator (same pattern, copied from here) that
    # a UUIDv7's hex is mostly its time-ordered high bits — truncating it
    # keeps almost no real randomness, proven by a genuine collision in a
    # same-millisecond test loop over there. Real random bits here instead.
    slug = re.sub(r"[^A-Z0-9]", "", lead.name.upper())[:6] or "LEAD"
    return f"{slug}-{secrets.token_hex(3).upper()}"


async def convert_lead(
    db: AsyncSession, *, organization_id: uuid.UUID, actor: Membership, lead_id: uuid.UUID
) -> LeadConversion:
    """ARCHITECTURE.md §3's one documented cross-module write: one
    transaction creates the Client and Project, stamps the lead's
    conversion fields, transitions its stage to WON, and records all three
    activity events (client.created/project.created ordinary feed,
    lead.converted audit) — all committed together.

    Codex P1: the archived/already-converted check was a bare check-then-
    write with no lock, so two concurrent conversions of the same lead
    could both pass it, each create their own Client+Project, then race to
    stamp `converted_client_id` — one client/project orphaned, conversion
    no longer one-to-one. `for_update=True` takes a row lock on the lead
    first; the second request blocks until the first commits, then
    (Postgres re-fetches the row under `FOR UPDATE` per READ COMMITTED)
    sees `converted_client_id` already set and 409s instead of racing."""
    ensure_actor_in_org(actor, organization_id)
    if actor.role not in _MANAGER_UP:
        raise ForbiddenError("Insufficient role to convert this lead")

    lead = await get_lead_in_org(
        db, organization_id=organization_id, lead_id=lead_id, for_update=True
    )
    if lead.archived_at is not None:
        raise ConflictError("Lead is archived")
    if lead.converted_client_id is not None:
        raise ConflictError("Lead has already been converted")

    org_session = OrgSession(db, organization_id=organization_id)

    client = Client(
        id=uuid7(),
        name=lead.name,
        company=lead.company,
        email=lead.email,
        phone=lead.phone,
        status=ClientStatus.ACTIVE,
        owner_id=actor.user_id,
    )
    org_session.add(client)
    await db.flush()

    project = Project(
        id=uuid7(),
        project_code=_project_code_from_lead(lead),
        name=lead.name,
        description=f"Converted from lead: {lead.name}",
        client_id=client.id,
        status=ProjectStatus.PLANNING,
        health=ProjectHealth.ON_TRACK,
        owner_id=actor.user_id,
        currency=lead.currency,
    )
    org_session.add(project)
    await db.flush()
    # The owner is always a project_members row (LEAD) — mirrors
    # project_service.create_project's own invariant.
    org_session.add(
        ProjectMember(
            id=uuid7(),
            project_id=project.id,
            user_id=actor.user_id,
            role_on_project=RoleOnProject.LEAD,
        )
    )

    lead.converted_client_id = client.id
    lead.converted_at = datetime.now(UTC)
    # Conversion always records a stage transition, even if the lead was
    # already at WON (ROADMAP.md Phase 3 Stage 5 decision) — conversion is
    # itself a significant pipeline event, not skipped as a no-op.
    await change_lead_stage(
        db,
        organization_id=organization_id,
        lead=lead,
        to_stage=LeadStage.WON,
        actor_id=actor.user_id,
    )

    await record(
        db,
        organization_id=organization_id,
        event="client.created",
        entity_type="client",
        entity_id=client.id,
        actor_id=actor.user_id,
        metadata={"name": client.name},
    )
    await record(
        db,
        organization_id=organization_id,
        event="project.created",
        entity_type="project",
        entity_id=project.id,
        actor_id=actor.user_id,
        metadata={"name": project.name, "project_code": project.project_code},
    )
    # MASTER_PROMPT §28: a permission-relevant change, same reasoning Phase
    # 2 used for project_member.added/removed.
    await record(
        db,
        organization_id=organization_id,
        event="lead.converted",
        entity_type="lead",
        entity_id=lead.id,
        actor_id=actor.user_id,
        metadata={"client_id": str(client.id), "project_id": str(project.id)},
        audit=True,
    )

    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        if _violates_constraint(exc, _PROJECT_CODE_CONSTRAINT):
            raise ConflictError("Generated project_code collided — retry the conversion") from None
        raise
    # lead was UPDATEd (not INSERTed) in this transaction — its
    # server_onupdate `updated_at` comes back expired, and a bare
    # lazy-reload on next access has no organization_id predicate, tripping
    # org_session.py's guard. Re-fetch it org-scoped, same fix update_lead
    # already applies for the identical reason. client/project were freshly
    # inserted, so their server defaults were already captured via
    # RETURNING at flush time — no re-fetch needed.
    refreshed_lead = await get_lead_in_org(db, organization_id=organization_id, lead_id=lead.id)
    return LeadConversion(lead=refreshed_lead, client=client, project=project)

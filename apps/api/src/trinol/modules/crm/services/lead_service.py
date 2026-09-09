from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from trinol.core.authz.permissions import Role
from trinol.core.db.org_session import OrgSession
from trinol.core.errors import AppError, ForbiddenError, NotFoundError, UnprocessableEntityError
from trinol.core.ids import uuid7
from trinol.modules.crm.models import Lead, LeadSource, LeadStage, LeadStageEvent
from trinol.modules.identity.models import Membership, MembershipStatus

_MANAGER_UP = (Role.MANAGER, Role.ADMIN, Role.OWNER)
_LEAD_CONTACT_CONSTRAINT = "ck_lead_contact"


@dataclass(frozen=True, slots=True)
class LeadList:
    items: list[Lead]
    total: int


def _violates_constraint(exc: IntegrityError, name: str) -> bool:
    current: BaseException | None = exc
    while current is not None:
        if getattr(current, "constraint_name", None) == name:
            return True
        current = current.__cause__
    return False


def ensure_actor_in_org(actor: Membership, organization_id: uuid.UUID) -> None:
    """Defense in depth, mirrors client_service.py's own copy of this
    guard — `crm` must not import `work` (ARCHITECTURE.md §3), so each
    module keeps its own trivial version rather than sharing one across the
    boundary."""
    if actor.organization_id != organization_id:
        raise ForbiddenError("Actor does not belong to this organization")


async def _get_active_membership_by_user(
    db: AsyncSession, *, organization_id: uuid.UUID, user_id: uuid.UUID
) -> Membership:
    result = await db.execute(
        select(Membership).where(
            Membership.organization_id == organization_id,
            Membership.user_id == user_id,
            Membership.status == MembershipStatus.ACTIVE,
        )
    )
    membership = result.scalar_one_or_none()
    if membership is None:
        raise AppError("assigned_to must reference an active membership in this organization")
    return membership


async def get_lead_in_org(
    db: AsyncSession, *, organization_id: uuid.UUID, lead_id: uuid.UUID
) -> Lead:
    """Org-scoped lookup — 404s a cross-org id exactly like a missing one
    (RBAC.md §4)."""
    result = await db.execute(
        select(Lead)
        .where(Lead.organization_id == organization_id, Lead.id == lead_id)
        .execution_options(populate_existing=True)
    )
    lead = result.scalar_one_or_none()
    if lead is None:
        raise NotFoundError("Lead not found")
    return lead


async def create_lead(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    actor: Membership,
    name: str,
    company: str | None,
    email: str | None,
    phone: str | None,
    source: LeadSource,
    service: str | None,
    estimated_value: Any,
    currency: str,
    stage: LeadStage,
    assigned_to: uuid.UUID | None,
    next_follow_up: Any,
    notes: str | None,
) -> Lead:
    ensure_actor_in_org(actor, organization_id)
    if actor.role not in _MANAGER_UP:
        raise ForbiddenError("Insufficient role to create a lead")

    if assigned_to is not None:
        await _get_active_membership_by_user(
            db, organization_id=organization_id, user_id=assigned_to
        )

    org_session = OrgSession(db, organization_id=organization_id)
    lead = Lead(
        id=uuid7(),
        name=name,
        company=company,
        email=email,
        phone=phone,
        source=source,
        service=service,
        estimated_value=estimated_value,
        currency=currency,
        stage=stage,
        assigned_to=assigned_to,
        next_follow_up=next_follow_up,
        notes=notes,
    )
    org_session.add(lead)
    await db.commit()
    return lead


async def list_leads(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    actor: Membership,
    stage: LeadStage | None = None,
    assigned_to: uuid.UUID | None = None,
    limit: int = 50,
    offset: int = 0,
) -> LeadList:
    ensure_actor_in_org(actor, organization_id)
    # ADR-0011: the list endpoint excludes archived rows. RBAC.md §2: view
    # is open to every role (ROADMAP.md Phase 3 Context decision — no
    # ownership-split rule for leads/clients this phase).
    filters: list[Any] = [Lead.archived_at.is_(None)]
    if stage is not None:
        filters.append(Lead.stage == stage)
    if assigned_to is not None:
        filters.append(Lead.assigned_to == assigned_to)

    total_result = await db.execute(
        select(func.count())
        .select_from(Lead)
        .where(Lead.organization_id == organization_id, *filters)
    )
    total = total_result.scalar_one()

    org_session = OrgSession(db, organization_id=organization_id)
    result = await db.execute(
        org_session.select(Lead)
        .where(*filters)
        .order_by(Lead.created_at.asc(), Lead.id.asc())
        .limit(limit)
        .offset(offset)
    )
    return LeadList(items=list(result.scalars().all()), total=total)


async def get_lead(
    db: AsyncSession, *, organization_id: uuid.UUID, actor: Membership, lead_id: uuid.UUID
) -> Lead:
    ensure_actor_in_org(actor, organization_id)
    return await get_lead_in_org(db, organization_id=organization_id, lead_id=lead_id)


async def change_lead_stage(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    lead: Lead,
    to_stage: LeadStage,
    actor_id: uuid.UUID | None,
) -> None:
    """DATABASE.md §3: `lead_stage_events` is "written in the same
    transaction as the stage change" — called from `update_lead` (a normal
    PATCH field) and from `work.services.lead_conversion_service.
    convert_lead` (Stage 5), never a standalone commit of its own; the
    caller's own commit covers both. Does not itself check `lead.stage !=
    to_stage` — callers already only call this when a real change is
    happening."""
    previous_stage = lead.stage
    lead.stage = to_stage
    org_session = OrgSession(db, organization_id=organization_id)
    org_session.add(
        LeadStageEvent(
            id=uuid7(),
            lead_id=lead.id,
            from_stage=previous_stage,
            to_stage=to_stage,
            actor_id=actor_id,
        )
    )
    await db.flush()


async def update_lead(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    actor: Membership,
    lead_id: uuid.UUID,
    updates: dict[str, Any],
) -> Lead:
    ensure_actor_in_org(actor, organization_id)
    if actor.role not in _MANAGER_UP:
        raise ForbiddenError("Insufficient role to edit this lead")
    lead = await get_lead_in_org(db, organization_id=organization_id, lead_id=lead_id)

    if "assigned_to" in updates and updates["assigned_to"] is not None:
        await _get_active_membership_by_user(
            db, organization_id=organization_id, user_id=updates["assigned_to"]
        )

    new_stage = updates.pop("stage", None)
    for field, value in updates.items():
        setattr(lead, field, value)

    if new_stage is not None and new_stage != lead.stage:
        await change_lead_stage(
            db,
            organization_id=organization_id,
            lead=lead,
            to_stage=new_stage,
            actor_id=actor.user_id,
        )

    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        if _violates_constraint(exc, _LEAD_CONTACT_CONSTRAINT):
            raise UnprocessableEntityError("email or phone is required") from None
        raise
    return await get_lead_in_org(db, organization_id=organization_id, lead_id=lead_id)


async def archive_lead(
    db: AsyncSession, *, organization_id: uuid.UUID, actor: Membership, lead_id: uuid.UUID
) -> Lead:
    """DELETE archives (ADR-0011), never a SQL DELETE. Reuses `LEAD_WRITE`'s
    MANAGER+ tier — RBAC.md has no distinct delete permission for leads,
    same stated assumption as `client_service.archive_client`."""
    ensure_actor_in_org(actor, organization_id)
    if actor.role not in _MANAGER_UP:
        raise ForbiddenError("Insufficient role to archive this lead")
    lead = await get_lead_in_org(db, organization_id=organization_id, lead_id=lead_id)
    lead.archived_at = datetime.now(UTC)
    await db.commit()
    return await get_lead_in_org(db, organization_id=organization_id, lead_id=lead_id)

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
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
from trinol.platform.activity import record

_MANAGER_UP = (Role.MANAGER, Role.ADMIN, Role.OWNER)
_LEAD_CONTACT_CONSTRAINT = "ck_lead_contact"


@dataclass(frozen=True, slots=True)
class LeadList:
    items: list[Lead]
    total: int


@dataclass(frozen=True, slots=True)
class LeadStats:
    pipeline_value: Decimal | None
    follow_ups_due: int


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
    db: AsyncSession, *, organization_id: uuid.UUID, lead_id: uuid.UUID, for_update: bool = False
) -> Lead:
    """Org-scoped lookup — 404s a cross-org id exactly like a missing one
    (RBAC.md §4). `for_update`: takes a row lock so a caller's own
    check-then-write on this lead (lead_conversion_service.convert_lead)
    serializes against a concurrent one instead of racing — same reason
    and shape as organization_lock.py's lock, just scoped to one row
    instead of the whole org."""
    stmt = (
        select(Lead)
        .where(Lead.organization_id == organization_id, Lead.id == lead_id)
        .execution_options(populate_existing=True)
    )
    if for_update:
        stmt = stmt.with_for_update()
    result = await db.execute(stmt)
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
    # ROADMAP.md Phase 2 decision 2: ordinary feed content, is_audit=false.
    await record(
        db,
        organization_id=organization_id,
        event="lead.created",
        entity_type="lead",
        entity_id=lead.id,
        actor_id=actor.user_id,
        # lead.source: no .value here — some existing test call sites pass
        # a plain string directly to this function rather than a real
        # LeadSource member (bypassing the schema layer's coercion); since
        # LeadSource is a StrEnum, both serialize identically into JSON
        # metadata either way, so this stays correct for both without
        # tightening what a direct service-level caller may pass.
        metadata={"name": lead.name, "source": lead.source},
    )
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


async def get_lead_stats(
    db: AsyncSession, *, organization_id: uuid.UUID, actor: Membership
) -> LeadStats:
    """ROADMAP.md Phase 3 Stage 8 decision: the dashboard's "Pipeline Value"
    and "Follow-ups due" tiles need a real aggregate, not a client-side sum
    over the (capped) pipeline board response — a small service-side query
    each, mirroring the `getCount` pattern the dashboard already uses for
    plain `{total}` counts. RBAC.md §2: view is open to every role, same as
    `list_leads`.

    ponytail: sums `estimated_value` across every open lead regardless of
    `currency` — every lead defaults to USD and nothing in this org's real
    usage mixes currencies today; a true multi-currency aggregate needs a
    per-currency breakdown or a conversion step, add it if that ever
    stops being true."""
    ensure_actor_in_org(actor, organization_id)
    open_stage_filters = [
        Lead.organization_id == organization_id,
        Lead.archived_at.is_(None),
        Lead.stage.not_in([LeadStage.WON, LeadStage.LOST]),
    ]
    pipeline_value_result = await db.execute(
        select(func.sum(Lead.estimated_value)).where(*open_stage_filters)
    )
    pipeline_value = pipeline_value_result.scalar_one_or_none()

    follow_ups_result = await db.execute(
        select(func.count())
        .select_from(Lead)
        .where(
            Lead.organization_id == organization_id,
            Lead.archived_at.is_(None),
            Lead.next_follow_up.is_not(None),
            Lead.next_follow_up <= date.today(),
        )
    )
    follow_ups_due = follow_ups_result.scalar_one()
    return LeadStats(pipeline_value=pipeline_value, follow_ups_due=follow_ups_due)


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
        previous_stage = lead.stage
        await change_lead_stage(
            db,
            organization_id=organization_id,
            lead=lead,
            to_stage=new_stage,
            actor_id=actor.user_id,
        )
        # ROADMAP.md Phase 2 decision 2: ordinary feed content, is_audit=
        # false. Recorded here, not inside change_lead_stage itself — that
        # function is also called directly by work.services.
        # lead_conversion_service.convert_lead (Stage 5), which already
        # records its own lead.converted *audit* event for the same
        # transition; recording here too would double-fire a second,
        # redundant feed event on every conversion.
        await record(
            db,
            organization_id=organization_id,
            event="lead.stage_changed",
            entity_type="lead",
            entity_id=lead.id,
            actor_id=actor.user_id,
            metadata={"from": previous_stage.value, "to": new_stage.value},
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

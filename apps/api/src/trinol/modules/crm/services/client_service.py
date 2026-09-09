from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from trinol.core.authz.permissions import Role
from trinol.core.db.org_session import OrgSession
from trinol.core.errors import AppError, ForbiddenError, NotFoundError
from trinol.core.ids import uuid7
from trinol.modules.crm.models import Client, ClientStatus
from trinol.modules.identity.models import Membership, MembershipStatus
from trinol.platform.activity import record

_MANAGER_UP = (Role.MANAGER, Role.ADMIN, Role.OWNER)


@dataclass(frozen=True, slots=True)
class ClientList:
    items: list[Client]
    total: int


def ensure_actor_in_org(actor: Membership, organization_id: uuid.UUID) -> None:
    """Defense in depth, mirrors modules/work/services/project_service.py's
    own copy of this guard — `crm` must not import `work` (ARCHITECTURE.md
    §3), so each module keeps its own trivial version rather than sharing
    one across the boundary."""
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
        raise AppError("owner_id must reference an active membership in this organization")
    return membership


async def get_client_in_org(
    db: AsyncSession, *, organization_id: uuid.UUID, client_id: uuid.UUID
) -> Client:
    """Org-scoped lookup — 404s a cross-org id exactly like a missing one
    (RBAC.md §4)."""
    result = await db.execute(
        select(Client)
        .where(Client.organization_id == organization_id, Client.id == client_id)
        .execution_options(populate_existing=True)
    )
    client = result.scalar_one_or_none()
    if client is None:
        raise NotFoundError("Client not found")
    return client


async def create_client(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    actor: Membership,
    name: str,
    company: str | None,
    email: str | None,
    phone: str | None,
    website: str | None,
    address: str | None,
    notes: str | None,
    status: ClientStatus,
    owner_id: uuid.UUID | None,
) -> Client:
    ensure_actor_in_org(actor, organization_id)
    if actor.role not in _MANAGER_UP:
        raise ForbiddenError("Insufficient role to create a client")

    if owner_id is not None:
        await _get_active_membership_by_user(db, organization_id=organization_id, user_id=owner_id)

    org_session = OrgSession(db, organization_id=organization_id)
    client = Client(
        id=uuid7(),
        name=name,
        company=company,
        email=email,
        phone=phone,
        website=website,
        address=address,
        notes=notes,
        status=status,
        owner_id=owner_id,
    )
    org_session.add(client)
    # ROADMAP.md Phase 2 decision 2: ordinary feed content, is_audit=false.
    await record(
        db,
        organization_id=organization_id,
        event="client.created",
        entity_type="client",
        entity_id=client.id,
        actor_id=actor.user_id,
        metadata={"name": client.name},
    )
    await db.commit()
    return client


async def list_clients(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    actor: Membership,
    limit: int = 50,
    offset: int = 0,
) -> ClientList:
    ensure_actor_in_org(actor, organization_id)
    # ADR-0011: the list endpoint excludes archived rows. RBAC.md §2: view
    # is open to every role (ROADMAP.md Phase 3 decision — no
    # ownership-split rule for leads/clients this phase).
    total_result = await db.execute(
        select(func.count())
        .select_from(Client)
        .where(Client.organization_id == organization_id, Client.archived_at.is_(None))
    )
    total = total_result.scalar_one()

    org_session = OrgSession(db, organization_id=organization_id)
    result = await db.execute(
        org_session.select(Client)
        .where(Client.archived_at.is_(None))
        .order_by(Client.created_at.asc(), Client.id.asc())
        .limit(limit)
        .offset(offset)
    )
    return ClientList(items=list(result.scalars().all()), total=total)


async def get_client(
    db: AsyncSession, *, organization_id: uuid.UUID, actor: Membership, client_id: uuid.UUID
) -> Client:
    ensure_actor_in_org(actor, organization_id)
    return await get_client_in_org(db, organization_id=organization_id, client_id=client_id)


async def update_client(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    actor: Membership,
    client_id: uuid.UUID,
    updates: dict[str, Any],
) -> Client:
    ensure_actor_in_org(actor, organization_id)
    if actor.role not in _MANAGER_UP:
        raise ForbiddenError("Insufficient role to edit this client")
    client = await get_client_in_org(db, organization_id=organization_id, client_id=client_id)

    if "owner_id" in updates and updates["owner_id"] is not None:
        await _get_active_membership_by_user(
            db, organization_id=organization_id, user_id=updates["owner_id"]
        )

    for field, value in updates.items():
        setattr(client, field, value)

    await db.commit()
    return await get_client_in_org(db, organization_id=organization_id, client_id=client_id)


async def archive_client(
    db: AsyncSession, *, organization_id: uuid.UUID, actor: Membership, client_id: uuid.UUID
) -> Client:
    """DELETE archives (ADR-0011), never a SQL DELETE. Reuses `CLIENT_WRITE`'s
    MANAGER+ tier — RBAC.md has no distinct delete permission for clients
    (unlike `PROJECT_DELETE`'s own ADMIN+ tier), stated assumption from
    ROADMAP.md's Phase 3 plan. No restore endpoint yet — not requested;
    `archived_at` is a plain column a future PATCH could clear if that
    becomes a real requirement."""
    ensure_actor_in_org(actor, organization_id)
    if actor.role not in _MANAGER_UP:
        raise ForbiddenError("Insufficient role to archive this client")
    client = await get_client_in_org(db, organization_id=organization_id, client_id=client_id)
    client.archived_at = datetime.now(UTC)
    await db.commit()
    return await get_client_in_org(db, organization_id=organization_id, client_id=client_id)

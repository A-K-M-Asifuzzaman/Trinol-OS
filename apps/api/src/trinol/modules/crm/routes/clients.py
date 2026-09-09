from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from trinol.core.authz.permissions import Permission
from trinol.core.authz.require import require
from trinol.core.db.engine import get_db_session
from trinol.modules.crm.models import Client
from trinol.modules.crm.schemas import (
    ClientCreateRequest,
    ClientListResponse,
    ClientResponse,
    ClientUpdateRequest,
)
from trinol.modules.crm.services.client_service import (
    archive_client,
    create_client,
    get_client,
    list_clients,
    update_client,
)
from trinol.modules.identity.deps import get_current_membership
from trinol.modules.identity.models import Membership

router = APIRouter(prefix="/api/v1/clients", tags=["crm"])


def _client_to_response(client: Client) -> ClientResponse:
    return ClientResponse(
        id=client.id,
        name=client.name,
        company=client.company,
        email=client.email,
        phone=client.phone,
        website=client.website,
        address=client.address,
        notes=client.notes,
        status=client.status,
        owner_id=client.owner_id,
        archived_at=client.archived_at,
        created_at=client.created_at,
        updated_at=client.updated_at,
    )


@router.post(
    "",
    response_model=ClientResponse,
    status_code=201,
    dependencies=[Depends(require(Permission.CLIENT_WRITE))],
)
async def create_client_route(
    payload: ClientCreateRequest,
    membership: Membership = Depends(get_current_membership),
    db: AsyncSession = Depends(get_db_session),
) -> ClientResponse:
    client = await create_client(
        db,
        organization_id=membership.organization_id,
        actor=membership,
        name=payload.name,
        company=payload.company,
        email=payload.email,
        phone=payload.phone,
        website=payload.website,
        address=payload.address,
        notes=payload.notes,
        status=payload.status,
        owner_id=payload.owner_id,
    )
    return _client_to_response(client)


@router.get(
    "", response_model=ClientListResponse, dependencies=[Depends(require(Permission.CLIENT_READ))]
)
async def list_clients_route(
    limit: int = Query(default=50, ge=1, le=200),  # ADR-0005: default 50, hard cap 200
    offset: int = Query(default=0, ge=0),
    membership: Membership = Depends(get_current_membership),
    db: AsyncSession = Depends(get_db_session),
) -> ClientListResponse:
    result = await list_clients(
        db, organization_id=membership.organization_id, actor=membership, limit=limit, offset=offset
    )
    return ClientListResponse(
        items=[_client_to_response(c) for c in result.items], total=result.total
    )


@router.get(
    "/{client_id}",
    response_model=ClientResponse,
    dependencies=[Depends(require(Permission.CLIENT_READ))],
)
async def get_client_route(
    client_id: uuid.UUID,
    membership: Membership = Depends(get_current_membership),
    db: AsyncSession = Depends(get_db_session),
) -> ClientResponse:
    client = await get_client(
        db, organization_id=membership.organization_id, actor=membership, client_id=client_id
    )
    return _client_to_response(client)


@router.patch(
    "/{client_id}",
    response_model=ClientResponse,
    dependencies=[Depends(require(Permission.CLIENT_WRITE))],
)
async def update_client_route(
    client_id: uuid.UUID,
    payload: ClientUpdateRequest,
    membership: Membership = Depends(get_current_membership),
    db: AsyncSession = Depends(get_db_session),
) -> ClientResponse:
    updates = payload.model_dump(exclude_unset=True)
    client = await update_client(
        db,
        organization_id=membership.organization_id,
        actor=membership,
        client_id=client_id,
        updates=updates,
    )
    return _client_to_response(client)


@router.delete(
    "/{client_id}",
    response_model=ClientResponse,
    dependencies=[Depends(require(Permission.CLIENT_WRITE))],
)
async def archive_client_route(
    client_id: uuid.UUID,
    membership: Membership = Depends(get_current_membership),
    db: AsyncSession = Depends(get_db_session),
) -> ClientResponse:
    client = await archive_client(
        db, organization_id=membership.organization_id, actor=membership, client_id=client_id
    )
    return _client_to_response(client)

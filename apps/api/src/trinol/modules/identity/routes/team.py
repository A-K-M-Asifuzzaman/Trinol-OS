from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from trinol.core.authz.permissions import Permission
from trinol.core.authz.require import require
from trinol.core.db.engine import get_db_session
from trinol.modules.identity.deps import get_current_membership
from trinol.modules.identity.models import Membership
from trinol.modules.identity.schemas import (
    MembershipListResponse,
    MembershipResponse,
    MembershipUpdateRequest,
)
from trinol.modules.identity.services.membership_service import change_role, remove_member
from trinol.modules.identity.services.team_service import TeamMember, get_member, list_members

router = APIRouter(prefix="/api/v1/memberships", tags=["team"])


def _to_response(member: TeamMember) -> MembershipResponse:
    return MembershipResponse(
        id=member.membership.id,
        user_id=member.user.id,
        full_name=member.user.full_name,
        email=member.user.email,
        avatar_url=member.user.avatar_url,
        role=member.membership.role,
        job_title=member.membership.job_title,
        status=member.membership.status,
        joined_at=member.membership.joined_at,
    )


@router.get(
    "",
    response_model=MembershipListResponse,
    dependencies=[Depends(require(Permission.TEAM_READ))],
)
async def list_team(
    limit: int = Query(default=50, ge=1, le=200),  # ADR-0005: default 50, hard cap 200
    offset: int = Query(default=0, ge=0),
    membership: Membership = Depends(get_current_membership),
    db: AsyncSession = Depends(get_db_session),
) -> MembershipListResponse:
    result = await list_members(
        db,
        organization_id=membership.organization_id,
        actor=membership,
        limit=limit,
        offset=offset,
    )
    return MembershipListResponse(
        items=[_to_response(member) for member in result.items], total=result.total
    )


@router.get(
    "/{membership_id}",
    response_model=MembershipResponse,
    dependencies=[Depends(require(Permission.TEAM_READ))],
)
async def get_team_member(
    membership_id: uuid.UUID,
    membership: Membership = Depends(get_current_membership),
    db: AsyncSession = Depends(get_db_session),
) -> MembershipResponse:
    member = await get_member(
        db,
        organization_id=membership.organization_id,
        actor=membership,
        membership_id=membership_id,
    )
    return _to_response(member)


@router.patch(
    "/{membership_id}",
    response_model=MembershipResponse,
    dependencies=[Depends(require(Permission.MEMBER_ROLE_WRITE))],
)
async def update_team_member(
    membership_id: uuid.UUID,
    payload: MembershipUpdateRequest,
    membership: Membership = Depends(get_current_membership),
    db: AsyncSession = Depends(get_db_session),
) -> MembershipResponse:
    # MEMBER_ROLE_WRITE and MEMBER_REMOVE are always granted together —
    # both are ADMIN-tier-only (RBAC.md §2), so no role ever holds one
    # without the other, and gating this route on MEMBER_ROLE_WRITE alone
    # covers the status branch below too. change_role/remove_member each
    # independently re-check actor.role in (ADMIN, OWNER) regardless
    # (defense in depth, same as every other membership-mutating path).
    #
    # The schema guarantees exactly one of role/status, never both: each
    # branch below is its own single, atomically-committed operation. Two
    # separate calls chained here (role change committed, then removal)
    # would not be atomic — a failure in the second would leave the first
    # durably persisted despite the request reporting a single failure.
    if payload.role is not None:
        await change_role(
            db,
            organization_id=membership.organization_id,
            actor=membership,
            target_membership_id=membership_id,
            new_role=payload.role,
        )
    else:
        assert payload.status is not None  # guaranteed by the schema validator
        await remove_member(
            db,
            organization_id=membership.organization_id,
            actor=membership,
            target_membership_id=membership_id,
        )

    member = await get_member(
        db,
        organization_id=membership.organization_id,
        actor=membership,
        membership_id=membership_id,
    )
    return _to_response(member)

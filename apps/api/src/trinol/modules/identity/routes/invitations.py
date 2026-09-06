from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from trinol.core.authz.permissions import Permission
from trinol.core.authz.require import public, require
from trinol.core.db.engine import get_db_session
from trinol.modules.identity.deps import get_current_membership
from trinol.modules.identity.models import Membership
from trinol.modules.identity.schemas import (
    InvitationCreateRequest,
    InvitationListResponse,
    InvitationPreviewResponse,
    InvitationResponse,
)
from trinol.modules.identity.services.invitation_service import (
    create_invitation,
    get_invitation_preview,
    list_open_invitations,
)
from trinol.platform.email.deps import get_email_sender
from trinol.platform.email.protocol import EmailSender

router = APIRouter(prefix="/api/v1/invitations", tags=["invitations"])


def _to_response(invitation: object) -> InvitationResponse:
    return InvitationResponse.model_validate(invitation, from_attributes=True)


@router.post(
    "",
    response_model=InvitationResponse,
    status_code=201,
    dependencies=[Depends(require(Permission.MEMBER_INVITE))],
)
async def invite_member(
    payload: InvitationCreateRequest,
    background_tasks: BackgroundTasks,
    membership: Membership = Depends(get_current_membership),
    db: AsyncSession = Depends(get_db_session),
    sender: EmailSender = Depends(get_email_sender),
) -> InvitationResponse:
    result = await create_invitation(
        db,
        organization_id=membership.organization_id,
        actor=membership,
        email=payload.email,
        role=payload.role,
    )
    # EMAIL.md §3: dispatched only after create_invitation's own commit above,
    # never blocking or failing this response.
    background_tasks.add_task(sender.send, result.email_message)
    return _to_response(result.invitation)


@router.get(
    "",
    response_model=InvitationListResponse,
    dependencies=[Depends(require(Permission.TEAM_READ))],
)
async def list_invitations(
    limit: int = Query(default=50, ge=1, le=200),  # ADR-0005: default 50, hard cap 200
    offset: int = Query(default=0, ge=0),
    membership: Membership = Depends(get_current_membership),
    db: AsyncSession = Depends(get_db_session),
) -> InvitationListResponse:
    result = await list_open_invitations(
        db,
        organization_id=membership.organization_id,
        actor=membership,
        limit=limit,
        offset=offset,
    )
    return InvitationListResponse(
        items=[_to_response(invitation) for invitation in result.items], total=result.total
    )


@router.get("/{token}", response_model=InvitationPreviewResponse)
@public  # AUTH.md §9 / decision 3: renders before the user signs into Firebase
async def preview_invitation(
    token: str,
    db: AsyncSession = Depends(get_db_session),
) -> InvitationPreviewResponse:
    preview = await get_invitation_preview(db, raw_token=token)
    return InvitationPreviewResponse.model_validate(preview, from_attributes=True)

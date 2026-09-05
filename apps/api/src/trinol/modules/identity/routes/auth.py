from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from trinol.core.db.engine import get_db_session
from trinol.core.deps import get_settings
from trinol.modules.identity.deps import get_identity_verifier
from trinol.modules.identity.identity_verifier import IdentityVerifier
from trinol.modules.identity.schemas import SessionExchangeRequest, SessionExchangeResponse
from trinol.modules.identity.services.session_service import exchange_session

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post("/session", response_model=SessionExchangeResponse)
async def create_session(
    payload: SessionExchangeRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db_session),
    verifier: IdentityVerifier = Depends(get_identity_verifier),
) -> SessionExchangeResponse:
    settings = get_settings()
    result = await exchange_session(
        db,
        verifier=verifier,
        id_token=payload.id_token,
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )

    response.set_cookie(
        key=settings.session_cookie_name,
        value=result.session_token,
        httponly=True,
        secure=settings.app_env != "local",  # AUTH.md §2: localhost dev is the only exception
        samesite="lax",
        path="/",
        # No max_age/expires: a session cookie, lifetime enforced server-side
        # against sessions.expires_at (AUTH.md §2).
    )

    return SessionExchangeResponse(
        user_id=str(result.user.id),
        organization_id=str(result.membership.organization_id),
        role=result.membership.role.value,
    )

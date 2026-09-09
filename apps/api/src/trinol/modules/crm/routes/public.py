from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from trinol.core.authz.require import public
from trinol.core.db.engine import get_db_session
from trinol.core.deps import get_settings
from trinol.core.errors import PayloadTooLargeError
from trinol.modules.crm.schemas import ContactSubmitRequest, ContactSubmitResponse
from trinol.modules.crm.services.contact_service import submit_contact
from trinol.modules.identity.models import Organization
from trinol.platform.email.deps import get_email_sender
from trinol.platform.email.protocol import EmailMessage, EmailSender

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/public", tags=["public"])

_MAX_BODY_BYTES = 8 * 1024

_organization_id_cache: uuid.UUID | None = None


async def get_public_contact_organization_id(
    db: AsyncSession = Depends(get_db_session),
) -> uuid.UUID:
    """DATABASE.md §3: the endpoint is unauthenticated, so there's no
    session to take organization_id from — it comes from
    PUBLIC_CONTACT_ORG_SLUG, resolved once and cached (mirrors
    platform.email.deps.get_email_sender's own module-level singleton
    pattern).

    DATABASE.md's literal wording is "resolved once at startup, failing the
    boot if it does not exist" — create_app() has no async lifespan hook to
    do that DB round trip against, and the setting is legitimately expected
    to stay unset in dev/test until this is configured for a real
    deployment (core/config.py's own comment on the field says as much), so
    a true boot-time hard fail would break every environment that hasn't
    configured it yet. This resolves lazily on first real request instead —
    still fails loudly the first time the route is actually hit if the slug
    is unset or doesn't match a real organization, just not at process
    boot. Tests override this dependency directly rather than exercising
    the real resolution (same pattern as get_email_sender/
    get_identity_verifier)."""
    global _organization_id_cache
    if _organization_id_cache is not None:
        return _organization_id_cache

    settings = get_settings()
    if not settings.public_contact_org_slug:
        raise RuntimeError("PUBLIC_CONTACT_ORG_SLUG is not configured")
    result = await db.execute(
        select(Organization.id).where(Organization.slug == settings.public_contact_org_slug)
    )
    organization_id = result.scalar_one_or_none()
    if organization_id is None:
        raise RuntimeError(
            f"PUBLIC_CONTACT_ORG_SLUG {settings.public_contact_org_slug!r} "
            "does not match a real organization"
        )
    _organization_id_cache = organization_id
    return organization_id


async def _enforce_body_size_cap(request: Request) -> None:
    """SECURITY.md §5: 8 KiB body cap, ahead of Pydantic parsing. No
    existing global body-size limit exists anywhere in the app to reuse
    (confirmed directly — there isn't one) — this route is the one that
    needs it, since it is the one write anybody on the internet can call
    with no authentication at all. Reads the real bytes rather than
    trusting Content-Length (a client can omit or lie about that header);
    Starlette caches the body after this call, so FastAPI's own
    Pydantic-parsing dependency downstream reads the same cached bytes,
    never the stream twice."""
    body = await request.body()
    if len(body) > _MAX_BODY_BYTES:
        raise PayloadTooLargeError("Request body exceeds the 8 KiB limit")


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


async def _send_and_log_failures(sender: EmailSender, message: EmailMessage) -> None:
    """SECURITY.md §5: "a mail failure never fails the HTTP response."
    invitation_service.py/routes/invitations.py's existing email flow
    schedules `background_tasks.add_task(sender.send, message)` bare — that
    only avoids surfacing a send failure to the caller because a *real*
    ASGI server (uvicorn) logs and swallows a background task's exception
    after the response is already on the wire. Verified directly (not
    assumed) that this is NOT true here: Starlette's TestClient/
    ASGITransport has no real network boundary to swallow it, so a bare
    add_task(sender.send, ...) re-raises straight into the caller. This
    route's requirement is explicit and stronger than the invitation flow's
    implicit one, so it catches the failure itself rather than leaning on
    which server happens to be driving the app."""
    try:
        await sender.send(message)
    except Exception:
        logger.exception("Failed to send a contact-flow email")


@router.post(
    "/contact",
    response_model=ContactSubmitResponse,
    status_code=202,
    dependencies=[Depends(_enforce_body_size_cap)],
)
@public
async def submit_contact_route(
    payload: ContactSubmitRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    organization_id: uuid.UUID = Depends(get_public_contact_organization_id),
    db: AsyncSession = Depends(get_db_session),
    sender: EmailSender = Depends(get_email_sender),
) -> ContactSubmitResponse:
    result = await submit_contact(
        db,
        organization_id=organization_id,
        name=payload.name,
        email=payload.email,
        phone=payload.phone,
        company=payload.company,
        service=payload.service,
        budget=payload.budget,
        message=payload.message,
        website=payload.website,
        rendered_at=payload.rendered_at,
        ip=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    # EMAIL.md §5 / SECURITY.md §5: queued after submit_contact's own
    # commit, never blocking or failing this response. Only present for a
    # real (non-spam) submission.
    if result.notification_email is not None:
        background_tasks.add_task(_send_and_log_failures, sender, result.notification_email)
    if result.confirmation_email is not None:
        background_tasks.add_task(_send_and_log_failures, sender, result.confirmation_email)
    return ContactSubmitResponse(reference_number=result.reference_number)

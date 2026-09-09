from __future__ import annotations

import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from trinol.core.db.org_session import OrgSession
from trinol.core.ids import uuid7
from trinol.modules.crm.models import ContactSubmission, Lead, LeadSource
from trinol.platform.email.protocol import EmailMessage
from trinol.platform.email.render import (
    render_contact_confirmation_email,
    render_new_lead_notification_email,
)
from trinol.platform.rate_limit import check_rate_limit

# SECURITY.md §5, exact numbers.
_IP_RATE_LIMIT = 5
_EMAIL_RATE_LIMIT = 20
_GLOBAL_RATE_LIMIT = 100
_RATE_WINDOW = timedelta(hours=1)

# ponytail: SECURITY.md §5 says "a minimum form-fill time" but names no
# number — 3 seconds is a made-up, common anti-bot heuristic, not a spec
# value. Raise it (or replace with a real behavioral signal) if bots are
# actually clearing it in production.
_MIN_FILL_DURATION = timedelta(seconds=3)

# A flat signal, not a graded probability — spam_score's NUMERIC(5,2) column
# supports finer scoring later if a real need for it appears (e.g. a
# Bayesian filter); today it's binary (was this flagged, yes/no).
_SPAM_SCORE = Decimal("1.00")

# hello@trinolit.com is hardcoded in EMAIL.md §5's own flow diagram — no
# dedicated setting exists (or is needed) for a single literal address.
_NOTIFICATION_RECIPIENT = "hello@trinolit.com"


@dataclass(frozen=True, slots=True)
class ContactSubmissionResult:
    reference_number: str
    # None for a spam/honeypot-flagged submission (SECURITY.md §5: neither
    # email is sent for it) — the route only queues what's actually here.
    notification_email: EmailMessage | None
    confirmation_email: EmailMessage | None


async def submit_contact(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    name: str,
    email: str,
    phone: str | None,
    company: str | None,
    service: str | None,
    budget: str | None,
    message: str,
    website: str,
    rendered_at: datetime,
    ip: str | None,
    user_agent: str | None,
) -> ContactSubmissionResult:
    """SECURITY.md §5's full flow, in order: rate limit (three keys, each
    committed immediately per platform.rate_limit's own contract — an
    attacker about to be rejected is still throttled) -> store the raw
    submission unconditionally -> create a Lead only for a real (non-spam)
    submission -> commit -> build (never send; the route sends via
    BackgroundTasks after this returns) the two emails, only for the
    non-spam case.
    """
    await check_rate_limit(
        db, key=f"contact:ip:{ip or 'unknown'}", window=_RATE_WINDOW, limit=_IP_RATE_LIMIT
    )
    await db.commit()
    await check_rate_limit(
        db, key=f"contact:email:{email}", window=_RATE_WINDOW, limit=_EMAIL_RATE_LIMIT
    )
    await db.commit()
    await check_rate_limit(db, key="contact:global", window=_RATE_WINDOW, limit=_GLOBAL_RATE_LIMIT)
    await db.commit()

    is_spam = website != "" or (datetime.now(UTC) - rendered_at) < _MIN_FILL_DURATION
    # secrets.token_hex, not uuid7().hex[:8]: proven empirically (a genuine
    # collision in a same-millisecond test loop) that truncating a UUIDv7's
    # hex to a handful of characters keeps mostly its time-ordered high bits
    # — real randomness, not apparent randomness that happens to look
    # random. ponytail: no retry-on-collision loop — 32 real random bits is
    # low-probability enough for this volume; add one if it ever actually
    # collides.
    reference_number = f"TRI-C-{secrets.token_hex(4).upper()}"

    org_session = OrgSession(db, organization_id=organization_id)
    submission = ContactSubmission(
        id=uuid7(),
        name=name,
        email=email,
        phone=phone,
        company=company,
        service=service,
        budget=budget,
        message=message,
        ip=ip,
        user_agent=user_agent,
        reference_number=reference_number,
        spam_score=_SPAM_SCORE if is_spam else None,
    )
    org_session.add(submission)
    await db.flush()

    if is_spam:
        await db.commit()
        return ContactSubmissionResult(
            reference_number=reference_number, notification_email=None, confirmation_email=None
        )

    lead = Lead(
        id=uuid7(),
        name=name,
        company=company,
        email=email,
        phone=phone,
        source=LeadSource.WEBSITE,
        service=service,
        notes=message,
    )
    org_session.add(lead)
    await db.flush()
    submission.lead_id = lead.id

    await db.commit()

    notification_html, notification_text = render_new_lead_notification_email(
        name=name,
        email=email,
        phone=phone,
        company=company,
        service=service,
        budget=budget,
        message=message,
        reference_number=reference_number,
    )
    notification_email = EmailMessage(
        to=_NOTIFICATION_RECIPIENT,
        subject=f"New lead: {name} — {service or 'General inquiry'}",
        html_body=notification_html,
        text_body=notification_text,
        # So the internal team can just hit reply to respond to the
        # customer directly (EMAIL.md §5 doesn't say so explicitly, but
        # nothing else makes sense for a lead-notification inbox).
        reply_to=email,
    )

    confirmation_html, confirmation_text = render_contact_confirmation_email(
        name=name, reference_number=reference_number, message=message
    )
    confirmation_email = EmailMessage(
        to=email,
        subject=f"We received your message — ref {reference_number}",
        html_body=confirmation_html,
        text_body=confirmation_text,
        # EMAIL.md §5: Reply-To is hello@trinolit.com; the customer's own
        # address is never used as From (structurally true regardless —
        # EmailMessage has no From field at all, it's bound to the sender
        # instance, never per-message).
        reply_to=_NOTIFICATION_RECIPIENT,
    )

    return ContactSubmissionResult(
        reference_number=reference_number,
        notification_email=notification_email,
        confirmation_email=confirmation_email,
    )

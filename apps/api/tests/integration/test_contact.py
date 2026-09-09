from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from httpx import AsyncClient
from sqlalchemy import select

import trinol.modules.crm.routes.public as public_module
from tests.factories import make_organization
from trinol.core.deps import get_settings
from trinol.modules.crm.models import ContactSubmission, Lead
from trinol.modules.crm.routes.public import get_public_contact_organization_id
from trinol.platform.email.protocol import EmailMessage

pytestmark = pytest.mark.usefixtures("db_session")

_MIN_FILL_SECONDS = 3


def _contact_origin_header() -> dict[str, str]:
    """SECURITY.md §5's origin exception activates only once
    PUBLIC_CONTACT_ORIGIN is configured — mirrors origin_check.py's own
    fallback exactly so this test behaves identically whether or not the
    running environment has it set (CI's env block doesn't; a local .env
    copied from .env.example does)."""
    settings = get_settings()
    return {"Origin": settings.public_contact_origin or settings.app_origin}


def _payload(**overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "name": "Jane Prospect",
        "email": "jane@prospect.test",
        "phone": None,
        "company": "Prospect Co",
        "service": "Web development",
        "budget": "$5k-$10k",
        "message": "We'd like a new website.",
        "website": "",
        "rendered_at": (datetime.now(UTC) - timedelta(seconds=_MIN_FILL_SECONDS + 5)).isoformat(),
    }
    body.update(overrides)
    return body


@pytest.fixture
async def contact_org(db_session):
    """Overrides get_public_contact_organization_id for the duration of the
    test — same dependency-override pattern fake_email_sender/fake_verifier
    already establish in conftest.py, just organization-shaped instead of a
    fixed singleton since each test needs its own fresh org."""
    from trinol.main import app

    org = await make_organization(db_session)
    await db_session.commit()
    app.dependency_overrides[get_public_contact_organization_id] = lambda: org.id
    try:
        yield org
    finally:
        app.dependency_overrides.pop(get_public_contact_organization_id, None)


class RaisingEmailSender:
    """Test double whose send() always raises — proves a mail failure
    can't surface past the response (SECURITY.md §5)."""

    async def send(self, message: EmailMessage) -> None:
        raise RuntimeError("SMTP is down")


async def test_happy_path_creates_submission_and_lead_and_queues_two_emails(
    client: AsyncClient, contact_org, fake_email_sender, db_session
) -> None:
    response = await client.post(
        "/api/public/contact", json=_payload(), headers=_contact_origin_header()
    )
    assert response.status_code == 202
    reference_number = response.json()["reference_number"]
    assert reference_number

    submission_result = await db_session.execute(
        select(ContactSubmission).where(ContactSubmission.organization_id == contact_org.id)
    )
    submission = submission_result.scalar_one()
    assert submission.reference_number == reference_number
    assert submission.spam_score is None
    assert submission.lead_id is not None
    assert submission.ip is not None

    lead_result = await db_session.execute(
        select(Lead).where(Lead.organization_id == contact_org.id)
    )
    lead = lead_result.scalar_one()
    assert lead.id == submission.lead_id
    assert lead.email == "jane@prospect.test"
    assert lead.source == "WEBSITE"

    assert len(fake_email_sender.sent) == 2
    notification = next(m for m in fake_email_sender.sent if m.to == "hello@trinolit.com")
    confirmation = next(m for m in fake_email_sender.sent if m.to == "jane@prospect.test")
    assert notification.reply_to == "jane@prospect.test"
    assert confirmation.reply_to == "hello@trinolit.com"


async def test_honeypot_filled_stores_submission_with_no_lead_and_no_emails(
    client: AsyncClient, contact_org, fake_email_sender, db_session
) -> None:
    response = await client.post(
        "/api/public/contact",
        json=_payload(website="http://spambot.example", email="spam1@x.com"),
        headers=_contact_origin_header(),
    )
    assert response.status_code == 202

    submission_result = await db_session.execute(
        select(ContactSubmission).where(
            ContactSubmission.organization_id == contact_org.id,
            ContactSubmission.email == "spam1@x.com",
        )
    )
    submission = submission_result.scalar_one()
    assert submission.spam_score is not None
    assert submission.lead_id is None

    lead_result = await db_session.execute(
        select(Lead).where(Lead.organization_id == contact_org.id, Lead.email == "spam1@x.com")
    )
    assert lead_result.scalar_one_or_none() is None
    assert fake_email_sender.sent == []


async def test_too_fast_submission_is_treated_as_spam(
    client: AsyncClient, contact_org, fake_email_sender, db_session
) -> None:
    response = await client.post(
        "/api/public/contact",
        json=_payload(rendered_at=datetime.now(UTC).isoformat(), email="spam2@x.com"),
        headers=_contact_origin_header(),
    )
    assert response.status_code == 202

    submission_result = await db_session.execute(
        select(ContactSubmission).where(
            ContactSubmission.organization_id == contact_org.id,
            ContactSubmission.email == "spam2@x.com",
        )
    )
    submission = submission_result.scalar_one()
    assert submission.spam_score is not None
    assert submission.lead_id is None
    assert fake_email_sender.sent == []


async def test_oversized_well_formed_body_is_rejected_before_parsing(
    client: AsyncClient, contact_org
) -> None:
    response = await client.post(
        "/api/public/contact",
        json=_payload(message="x" * 9000),
        headers=_contact_origin_header(),
    )
    assert response.status_code == 413


async def test_oversized_malformed_body_is_rejected_before_parsing(
    client: AsyncClient, contact_org
) -> None:
    """Codex P1: a route-level Depends(...) body-size check runs too late —
    FastAPI reads and JSON-decodes the body as part of resolving the
    endpoint's own body parameter, and a *malformed* body's decode failure
    short-circuits to 422 before any dependency (route-level or not) ever
    runs at all, so a well-formed-oversized test alone doesn't prove
    anything about this case. Enforcement moved to BodySizeCapMiddleware
    (pure ASGI, runs before FastAPI's routing/dependency machinery even
    starts) specifically to catch this — garbage bytes that are neither
    valid JSON nor within the cap must still 413, never reach a parser."""
    response = await client.post(
        "/api/public/contact",
        content=b"{not valid json" + b"x" * 9000,
        headers={**_contact_origin_header(), "Content-Type": "application/json"},
    )
    assert response.status_code == 413


async def test_mail_send_failure_never_fails_the_response(client: AsyncClient, contact_org) -> None:
    from trinol.main import app
    from trinol.platform.email.deps import get_email_sender

    app.dependency_overrides[get_email_sender] = lambda: RaisingEmailSender()
    try:
        response = await client.post(
            "/api/public/contact",
            json=_payload(email="mailfail@x.com"),
            headers=_contact_origin_header(),
        )
    finally:
        app.dependency_overrides.pop(get_email_sender, None)
    assert response.status_code == 202


async def test_sixth_request_from_the_same_ip_within_an_hour_is_rate_limited(
    client: AsyncClient, contact_org
) -> None:
    headers = _contact_origin_header()
    for i in range(5):
        response = await client.post(
            "/api/public/contact",
            json=_payload(email=f"budget{i}@x.com"),
            headers=headers,
        )
        assert response.status_code == 202, f"request {i} unexpectedly failed: {response.text}"

    sixth = await client.post(
        "/api/public/contact", json=_payload(email="budget-sixth@x.com"), headers=headers
    )
    assert sixth.status_code == 429
    assert "Retry-After" in sixth.headers
    assert int(sixth.headers["Retry-After"]) > 0


async def test_organization_resolver_fails_loudly_when_slug_unset(
    db_session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Proves the "fails loudly" half of get_public_contact_organization_id's
    deliberate deviation from DATABASE.md's literal "fails the boot"
    wording (see the function's own docstring) — every route-level test
    above overrides this dependency entirely and never exercises the real
    body, so this calls it directly instead. Resets the module's cache via
    monkeypatch so this can't leak into (or be contaminated by) any other
    test in the same process."""
    monkeypatch.setattr(public_module, "_organization_id_cache", None)
    monkeypatch.setattr(
        public_module, "get_settings", lambda: SimpleNamespace(public_contact_org_slug=None)
    )

    with pytest.raises(RuntimeError, match="not configured"):
        await public_module.get_public_contact_organization_id(db=db_session)


async def test_organization_resolver_fails_loudly_when_slug_does_not_match(
    db_session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(public_module, "_organization_id_cache", None)
    monkeypatch.setattr(
        public_module,
        "get_settings",
        lambda: SimpleNamespace(public_contact_org_slug="does-not-exist"),
    )

    with pytest.raises(RuntimeError, match="does not match"):
        await public_module.get_public_contact_organization_id(db=db_session)

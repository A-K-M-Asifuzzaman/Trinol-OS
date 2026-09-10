from __future__ import annotations

import asyncio
from datetime import date
from decimal import Decimal

import pytest
from dotenv import dotenv_values
from httpx import AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import create_async_engine

from tests.factories import make_client, make_invoice, make_membership, make_organization, make_user
from tests.helpers import login_as, login_as_existing
from trinol.core.authz.permissions import Role
from trinol.core.config import _ENV_FILE
from trinol.core.db.engine import get_session_factory
from trinol.modules.crm.models import Client
from trinol.modules.finance.models import Invoice, InvoiceCounter, InvoiceItem, InvoiceStatus
from trinol.modules.finance.services.invoice_service import LineItemInput, create_invoice
from trinol.modules.identity.models import Membership, Organization, User
from trinol.platform.activity import list_audit, list_feed
from trinol.platform.models import ActivityEvent

pytestmark = pytest.mark.usefixtures("db_session")


def _client_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "issue_date": "2026-01-01",
        "due_date": "2026-01-15",
        "items": [
            {"description": "Consulting", "quantity": "1", "unit_price": "1000.00"},
        ],
    }
    payload.update(overrides)
    return payload


@pytest.mark.parametrize("role", [Role.ADMIN, Role.OWNER])
async def test_admin_and_up_can_create_invoice(
    client: AsyncClient, fake_verifier, db_session, role: Role
) -> None:
    """RBAC.md §2: "Invoices: create/send" is ADMIN+-tier only."""
    actor = await login_as(client, fake_verifier, db_session, role=role)
    client_row = await make_client(db_session, organization=actor.organization)
    await db_session.commit()

    response = await client.post(
        "/api/v1/finance/invoices",
        json=_client_payload(client_id=str(client_row.id)),
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["invoice_number"].startswith("TRI-2026-")
    assert body["status"] == "DRAFT"
    assert body["subtotal"] == "1000.00"
    assert body["total"] == "1000.00"
    assert body["is_overdue"] is False
    assert len(body["items"]) == 1
    assert body["items"][0]["line_total"] == "1000.00"


@pytest.mark.parametrize("role", [Role.MEMBER, Role.MANAGER])
async def test_member_and_manager_cannot_create_invoice(
    client: AsyncClient, fake_verifier, db_session, role: Role
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=role)
    client_row = await make_client(db_session, organization=actor.organization)
    await db_session.commit()

    response = await client.post(
        "/api/v1/finance/invoices",
        json=_client_payload(client_id=str(client_row.id)),
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == 403


async def test_invoice_numbers_are_sequential_per_org_and_year(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.OWNER)
    client_row = await make_client(db_session, organization=actor.organization)
    await db_session.commit()

    first = await client.post(
        "/api/v1/finance/invoices",
        json=_client_payload(client_id=str(client_row.id)),
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    second = await client.post(
        "/api/v1/finance/invoices",
        json=_client_payload(client_id=str(client_row.id)),
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert first.json()["invoice_number"] == "TRI-2026-0001"
    assert second.json()["invoice_number"] == "TRI-2026-0002"


async def test_rounding_exposed_by_repeated_thirds(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    """ADR-0007's own consequences section: 'Tests must include values
    that expose rounding (33.33 × 3, ...)' — three units at 33.33 sum to
    99.99, one cent short of 100.00, and must be computed exactly, not
    silently corrected."""
    actor = await login_as(client, fake_verifier, db_session, role=Role.OWNER)
    client_row = await make_client(db_session, organization=actor.organization)
    await db_session.commit()

    response = await client.post(
        "/api/v1/finance/invoices",
        json=_client_payload(
            client_id=str(client_row.id),
            items=[{"description": "Thirds", "quantity": "3", "unit_price": "33.33"}],
        ),
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["items"][0]["line_total"] == "99.99"
    assert body["subtotal"] == "99.99"
    assert body["total"] == "99.99"


async def test_rounding_exposed_by_three_decimal_quantity(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    """ADR-0007's own consequences section: '... 3-decimal quantities ...'
    — quantity=0.333 (NUMERIC(12,3)'s own precision) at 30.00/unit rounds
    to 9.99, not 10.00."""
    actor = await login_as(client, fake_verifier, db_session, role=Role.OWNER)
    client_row = await make_client(db_session, organization=actor.organization)
    await db_session.commit()

    response = await client.post(
        "/api/v1/finance/invoices",
        json=_client_payload(
            client_id=str(client_row.id),
            items=[{"description": "Partial unit", "quantity": "0.333", "unit_price": "30.00"}],
        ),
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == 201
    assert response.json()["items"][0]["line_total"] == "9.99"


async def test_discount_larger_than_subtotal_is_rejected(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    """ADR-0007's own consequences section: '... a discount larger than a
    line'. `ck_invoice_amounts`/`ck_invoice_total` require every amount
    (including the derived total) to stay non-negative — this must be
    rejected with a clean 422, not a raw DB CheckViolationError."""
    actor = await login_as(client, fake_verifier, db_session, role=Role.OWNER)
    client_row = await make_client(db_session, organization=actor.organization)
    await db_session.commit()

    response = await client.post(
        "/api/v1/finance/invoices",
        json=_client_payload(
            client_id=str(client_row.id),
            items=[{"description": "Small item", "quantity": "1", "unit_price": "10.00"}],
            discount_amount="20.00",
        ),
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == 422


async def test_due_date_before_issue_date_is_rejected(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.OWNER)
    client_row = await make_client(db_session, organization=actor.organization)
    await db_session.commit()

    response = await client.post(
        "/api/v1/finance/invoices",
        json=_client_payload(
            client_id=str(client_row.id), issue_date="2026-01-15", due_date="2026-01-01"
        ),
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == 422


async def test_create_invoice_rejects_client_not_in_organization(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.OWNER)
    other_org = await make_organization(db_session)
    other_client = await make_client(db_session, organization=other_org)
    await db_session.commit()

    response = await client.post(
        "/api/v1/finance/invoices",
        json=_client_payload(client_id=str(other_client.id)),
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == 404


async def test_admin_can_list_and_get_invoice(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.ADMIN)
    client_row = await make_client(db_session, organization=actor.organization)
    seeded = await make_invoice(
        db_session, organization=actor.organization, client=client_row, created_by=actor.membership
    )
    await db_session.commit()

    list_response = await client.get("/api/v1/finance/invoices")
    assert list_response.status_code == 200
    assert any(item["id"] == str(seeded.id) for item in list_response.json()["items"])

    get_response = await client.get(f"/api/v1/finance/invoices/{seeded.id}")
    assert get_response.status_code == 200
    assert get_response.json()["invoice_number"] == seeded.invoice_number


async def test_overdue_is_derived_not_stored(
    client: AsyncClient, fake_verifier, db_session
) -> None:

    actor = await login_as(client, fake_verifier, db_session, role=Role.ADMIN)
    client_row = await make_client(db_session, organization=actor.organization)
    overdue_invoice = await make_invoice(
        db_session,
        organization=actor.organization,
        client=client_row,
        created_by=actor.membership,
        issue_date=date(2020, 1, 1),
        due_date=date(2020, 1, 15),
        status=InvoiceStatus.SENT,
    )
    draft_invoice = await make_invoice(
        db_session,
        organization=actor.organization,
        client=client_row,
        created_by=actor.membership,
        issue_date=date(2020, 1, 1),
        due_date=date(2020, 1, 15),
        status=InvoiceStatus.DRAFT,
    )
    await db_session.commit()

    overdue_response = await client.get(f"/api/v1/finance/invoices/{overdue_invoice.id}")
    assert overdue_response.json()["is_overdue"] is True

    draft_response = await client.get(f"/api/v1/finance/invoices/{draft_invoice.id}")
    assert draft_response.json()["is_overdue"] is False


async def test_update_draft_invoice_recomputes_totals(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.OWNER)
    client_row = await make_client(db_session, organization=actor.organization)
    await db_session.commit()

    create_response = await client.post(
        "/api/v1/finance/invoices",
        json=_client_payload(client_id=str(client_row.id)),
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    invoice_id = create_response.json()["id"]

    update_response = await client.patch(
        f"/api/v1/finance/invoices/{invoice_id}",
        json={
            "items": [{"description": "Revised scope", "quantity": "2", "unit_price": "250.00"}],
            "notes": "Updated",
        },
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert update_response.status_code == 200
    body = update_response.json()
    assert len(body["items"]) == 1
    assert body["items"][0]["description"] == "Revised scope"
    assert body["subtotal"] == "500.00"
    assert body["total"] == "500.00"
    assert body["notes"] == "Updated"


async def test_update_non_draft_invoice_is_rejected(
    client: AsyncClient, fake_verifier, db_session
) -> None:

    actor = await login_as(client, fake_verifier, db_session, role=Role.OWNER)
    client_row = await make_client(db_session, organization=actor.organization)
    sent_invoice = await make_invoice(
        db_session,
        organization=actor.organization,
        client=client_row,
        created_by=actor.membership,
        status=InvoiceStatus.SENT,
    )
    await db_session.commit()

    response = await client.patch(
        f"/api/v1/finance/invoices/{sent_invoice.id}",
        json={"notes": "hijack"},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == 409


async def test_send_invoice_transitions_status_and_dispatches_email(
    client: AsyncClient, fake_verifier, db_session, fake_email_sender
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.OWNER)
    client_row = await make_client(
        db_session, organization=actor.organization, email="client@x.com"
    )
    await db_session.commit()

    create_response = await client.post(
        "/api/v1/finance/invoices",
        json=_client_payload(client_id=str(client_row.id)),
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    invoice_id = create_response.json()["id"]

    response = await client.post(
        f"/api/v1/finance/invoices/{invoice_id}/send",
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "SENT"
    assert body["sent_at"] is not None

    assert len(fake_email_sender.sent) == 1
    message = fake_email_sender.sent[0]
    assert message.to == "client@x.com"
    assert body["invoice_number"] in message.subject
    assert body["invoice_number"] in message.text_body


async def test_send_invoice_rejects_client_with_no_email(
    client: AsyncClient, fake_verifier, db_session, fake_email_sender
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.OWNER)
    client_row = await make_client(db_session, organization=actor.organization)
    assert client_row.email is None
    await db_session.commit()

    create_response = await client.post(
        "/api/v1/finance/invoices",
        json=_client_payload(client_id=str(client_row.id)),
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    invoice_id = create_response.json()["id"]

    response = await client.post(
        f"/api/v1/finance/invoices/{invoice_id}/send",
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == 422
    assert fake_email_sender.sent == []


async def test_sending_a_non_draft_invoice_is_rejected(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.OWNER)
    client_row = await make_client(db_session, organization=actor.organization, email="c@x.com")
    sent_invoice = await make_invoice(
        db_session,
        organization=actor.organization,
        client=client_row,
        created_by=actor.membership,
        status=InvoiceStatus.SENT,
    )
    await db_session.commit()

    response = await client.post(
        f"/api/v1/finance/invoices/{sent_invoice.id}/send",
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == 409


@pytest.mark.parametrize(
    "status", [InvoiceStatus.DRAFT, InvoiceStatus.SENT, InvoiceStatus.PARTIALLY_PAID]
)
async def test_cancel_invoice_from_non_terminal_status(
    client: AsyncClient, fake_verifier, db_session, status: InvoiceStatus
) -> None:
    """ADR-0007: 'Cancellation is a status change with an audit event,
    never a delete' — every non-terminal status may transition to
    CANCELLED."""
    actor = await login_as(client, fake_verifier, db_session, role=Role.OWNER)
    client_row = await make_client(db_session, organization=actor.organization)
    invoice = await make_invoice(
        db_session,
        organization=actor.organization,
        client=client_row,
        created_by=actor.membership,
        status=status,
    )
    await db_session.commit()

    response = await client.post(
        f"/api/v1/finance/invoices/{invoice.id}/cancel",
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "CANCELLED"


@pytest.mark.parametrize("status", [InvoiceStatus.PAID, InvoiceStatus.CANCELLED])
async def test_cancel_invoice_from_terminal_status_is_rejected(
    client: AsyncClient, fake_verifier, db_session, status: InvoiceStatus
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.OWNER)
    client_row = await make_client(db_session, organization=actor.organization)
    invoice = await make_invoice(
        db_session,
        organization=actor.organization,
        client=client_row,
        created_by=actor.membership,
        status=status,
    )
    await db_session.commit()

    response = await client.post(
        f"/api/v1/finance/invoices/{invoice.id}/cancel",
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == 409


async def test_cancel_invoice_is_audited_and_absent_from_ordinary_feed(
    client: AsyncClient, fake_verifier, db_session
) -> None:

    actor = await login_as(client, fake_verifier, db_session, role=Role.OWNER)
    client_row = await make_client(db_session, organization=actor.organization)
    invoice = await make_invoice(
        db_session, organization=actor.organization, client=client_row, created_by=actor.membership
    )
    await db_session.commit()

    response = await client.post(
        f"/api/v1/finance/invoices/{invoice.id}/cancel",
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == 200

    audit_rows = await list_audit(db_session, organization_id=actor.organization.id)
    cancelled_events = [row for row in audit_rows if row.event == "invoice.cancelled"]
    assert len(cancelled_events) == 1
    assert str(cancelled_events[0].entity_id) == str(invoice.id)

    feed_result = await list_feed(db_session, organization_id=actor.organization.id)
    feed_events = [row for row in feed_result if row.event == "invoice.cancelled"]
    assert feed_events == []


@pytest.mark.parametrize("role", [Role.MEMBER, Role.MANAGER])
async def test_member_and_manager_cannot_cancel_invoice(
    client: AsyncClient, fake_verifier, db_session, role: Role
) -> None:
    """Same org as the invoice — proves the 403 is the role-tier check
    (INVOICE_CANCEL is ADMIN+-only), not merely a cross-org 404 in
    disguise."""
    org = await make_organization(db_session)
    owner_user = await make_user(db_session, email=f"cancel-owner-{org.id}@x.com")
    owner = await make_membership(db_session, organization=org, user=owner_user, role=Role.OWNER)
    client_row = await make_client(db_session, organization=org)
    invoice = await make_invoice(db_session, organization=org, client=client_row, created_by=owner)
    await db_session.commit()

    actor_user = await make_user(db_session, email=f"cancel-actor-{org.id}-{role.value}@x.com")
    actor_membership = await make_membership(
        db_session, organization=org, user=actor_user, role=role
    )
    await db_session.commit()
    actor = await login_as_existing(
        client, fake_verifier, user=actor_user, membership=actor_membership, organization=org
    )

    response = await client.post(
        f"/api/v1/finance/invoices/{invoice.id}/cancel",
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == 403


async def test_invoice_in_another_org_is_404(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    other_org = await make_organization(db_session)
    other_owner = await make_user(db_session, email=f"owner-{other_org.id}@x.com")
    other_actor = await make_membership(
        db_session, organization=other_org, user=other_owner, role=Role.OWNER
    )
    other_client = await make_client(db_session, organization=other_org)
    other_invoice = await make_invoice(
        db_session, organization=other_org, client=other_client, created_by=other_actor
    )
    await db_session.commit()

    actor = await login_as(client, fake_verifier, db_session, role=Role.ADMIN)

    get_response = await client.get(f"/api/v1/finance/invoices/{other_invoice.id}")
    assert get_response.status_code == 404

    patch_response = await client.patch(
        f"/api/v1/finance/invoices/{other_invoice.id}",
        json={"notes": "hijack"},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert patch_response.status_code == 404


async def test_concurrent_invoice_creation_never_produces_duplicate_numbers() -> None:
    """ADR-0007: 'Concurrent-payment tests are required to prove that two
    requests cannot both pass the balance check' — the same discipline
    applies to invoice numbering, whose own consequences bullet says
    'Concurrency on invoice numbering is handled by a row lock, tested by
    a concurrent-creation test.' Needs two genuinely independent DB
    connections, not two SAVEPOINTs sharing one transaction — same
    approach and reason as test_lead_conversion.py's own concurrent-
    conversion race test. Real commits, no test fixtures — cleaned up
    explicitly at the end, following the FULL FK-ordered cleanup that
    test (and its own follow-up fix) established, not just the
    activity_events part."""
    session_factory = get_session_factory()

    setup_session = session_factory()
    try:
        org = await make_organization(setup_session)
        owner_user = await make_user(setup_session, email=f"owner-{org.id}@x.com")
        owner = await make_membership(
            setup_session, organization=org, user=owner_user, role=Role.OWNER
        )
        client_row = await make_client(setup_session, organization=org)
        await setup_session.commit()
        org_id, owner_id, client_id = org.id, owner.id, client_row.id
        owner_user_id = owner_user.id
    finally:
        await setup_session.close()

    session_1 = session_factory()
    session_2 = session_factory()
    try:
        actor_1 = (
            await session_1.execute(
                select(Membership).where(
                    Membership.organization_id == org_id, Membership.id == owner_id
                )
            )
        ).scalar_one()
        actor_2 = (
            await session_2.execute(
                select(Membership).where(
                    Membership.organization_id == org_id, Membership.id == owner_id
                )
            )
        ).scalar_one()

        items = [
            LineItemInput(description="Work", quantity=Decimal("1"), unit_price=Decimal("100.00"))
        ]
        results = await asyncio.gather(
            create_invoice(
                session_1,
                organization_id=org_id,
                actor=actor_1,
                client_id=client_id,
                project_id=None,
                issue_date=date(2026, 1, 1),
                due_date=date(2026, 1, 15),
                currency="USD",
                items=items,
                discount_amount=Decimal("0"),
                tax_amount=Decimal("0"),
                notes=None,
                terms=None,
            ),
            create_invoice(
                session_2,
                organization_id=org_id,
                actor=actor_2,
                client_id=client_id,
                project_id=None,
                issue_date=date(2026, 1, 1),
                due_date=date(2026, 1, 15),
                currency="USD",
                items=items,
                discount_amount=Decimal("0"),
                tax_amount=Decimal("0"),
                notes=None,
                terms=None,
            ),
            return_exceptions=True,
        )

        for result in results:
            if isinstance(result, BaseException):
                raise result

        numbers = {pair.invoice.invoice_number for pair in results}
        assert len(numbers) == 2, f"expected two distinct invoice numbers, got: {numbers}"
    finally:
        await session_1.close()
        await session_2.close()

        # See test_lead_conversion.py's matching cleanup: trinol_app is
        # REVOKEd from UPDATE/DELETE on activity_events (ADR-0006), so the
        # two invoice.created activity rows need the migrator role.
        migration_url = dotenv_values(_ENV_FILE)["DATABASE_MIGRATION_URL"]
        assert migration_url is not None
        migrator_engine = create_async_engine(migration_url)
        try:
            async with migrator_engine.begin() as conn:
                await conn.execute(
                    ActivityEvent.__table__.delete().where(ActivityEvent.organization_id == org_id)
                )
        finally:
            await migrator_engine.dispose()

        # FK-ordered: InvoiceItem (child of Invoice) before Invoice, then
        # InvoiceCounter/Client/Membership/User/Organization.
        cleanup_session = session_factory()
        try:
            await cleanup_session.execute(
                delete(InvoiceItem).where(InvoiceItem.organization_id == org_id)
            )
            await cleanup_session.execute(delete(Invoice).where(Invoice.organization_id == org_id))
            await cleanup_session.execute(
                delete(InvoiceCounter).where(InvoiceCounter.organization_id == org_id)
            )
            await cleanup_session.execute(delete(Client).where(Client.organization_id == org_id))
            await cleanup_session.execute(
                delete(Membership).where(Membership.organization_id == org_id)
            )
            await cleanup_session.execute(delete(User).where(User.id == owner_user_id))
            await cleanup_session.execute(delete(Organization).where(Organization.id == org_id))
            await cleanup_session.commit()
        finally:
            await cleanup_session.close()

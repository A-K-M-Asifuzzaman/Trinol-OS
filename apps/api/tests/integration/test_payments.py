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
from tests.helpers import login_as
from trinol.core.authz.permissions import Role
from trinol.core.config import _ENV_FILE
from trinol.core.db.engine import get_session_factory
from trinol.core.errors import ConflictError
from trinol.modules.crm.models import Client
from trinol.modules.finance.models import Invoice, InvoiceItem, InvoiceStatus, Payment
from trinol.modules.finance.services.payment_service import record_payment
from trinol.modules.identity.models import Membership, Organization, User
from trinol.platform.models import ActivityEvent

pytestmark = pytest.mark.usefixtures("db_session")


async def _make_sent_invoice(
    db_session, *, organization, client_row, created_by, total: Decimal = Decimal("100.00")
) -> Invoice:
    return await make_invoice(
        db_session,
        organization=organization,
        client=client_row,
        created_by=created_by,
        subtotal=total,
        status=InvoiceStatus.SENT,
    )


@pytest.mark.parametrize("role", [Role.ADMIN, Role.OWNER])
async def test_admin_and_up_can_record_partial_payment(
    client: AsyncClient, fake_verifier, db_session, role: Role
) -> None:
    """RBAC.md §2: "Record payment" is ADMIN+-tier only."""
    actor = await login_as(client, fake_verifier, db_session, role=role)
    client_row = await make_client(db_session, organization=actor.organization)
    invoice = await _make_sent_invoice(
        db_session,
        organization=actor.organization,
        client_row=client_row,
        created_by=actor.membership,
    )
    await db_session.commit()

    response = await client.post(
        f"/api/v1/finance/invoices/{invoice.id}/payments",
        json={"amount": "40.00", "paid_on": "2026-02-01", "method": "bank_transfer"},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["amount"] == "40.00"
    assert body["invoice_id"] == str(invoice.id)

    invoice_response = await client.get(f"/api/v1/finance/invoices/{invoice.id}")
    assert invoice_response.json()["status"] == "PARTIALLY_PAID"
    assert invoice_response.json()["amount_paid"] == "40.00"


@pytest.mark.parametrize("role", [Role.MEMBER, Role.MANAGER])
async def test_member_and_manager_cannot_record_payment(
    client: AsyncClient, fake_verifier, db_session, role: Role
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=role)
    client_row = await make_client(db_session, organization=actor.organization)
    invoice = await _make_sent_invoice(
        db_session,
        organization=actor.organization,
        client_row=client_row,
        created_by=actor.membership,
    )
    await db_session.commit()

    response = await client.post(
        f"/api/v1/finance/invoices/{invoice.id}/payments",
        json={"amount": "40.00", "paid_on": "2026-02-01", "method": "cash"},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == 403


async def test_full_payment_marks_invoice_paid(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.OWNER)
    client_row = await make_client(db_session, organization=actor.organization)
    invoice = await _make_sent_invoice(
        db_session,
        organization=actor.organization,
        client_row=client_row,
        created_by=actor.membership,
    )
    await db_session.commit()

    response = await client.post(
        f"/api/v1/finance/invoices/{invoice.id}/payments",
        json={"amount": "100.00", "paid_on": "2026-02-01", "method": "bank_transfer"},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == 201

    invoice_response = await client.get(f"/api/v1/finance/invoices/{invoice.id}")
    assert invoice_response.json()["status"] == "PAID"
    assert invoice_response.json()["amount_paid"] == "100.00"


async def test_two_partial_payments_complete_the_invoice(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.OWNER)
    client_row = await make_client(db_session, organization=actor.organization)
    invoice = await _make_sent_invoice(
        db_session,
        organization=actor.organization,
        client_row=client_row,
        created_by=actor.membership,
    )
    await db_session.commit()

    first = await client.post(
        f"/api/v1/finance/invoices/{invoice.id}/payments",
        json={"amount": "60.00", "paid_on": "2026-02-01", "method": "cash"},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert first.status_code == 201
    mid_response = await client.get(f"/api/v1/finance/invoices/{invoice.id}")
    assert mid_response.json()["status"] == "PARTIALLY_PAID"

    second = await client.post(
        f"/api/v1/finance/invoices/{invoice.id}/payments",
        json={"amount": "40.00", "paid_on": "2026-02-02", "method": "cash"},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert second.status_code == 201
    final_response = await client.get(f"/api/v1/finance/invoices/{invoice.id}")
    assert final_response.json()["status"] == "PAID"
    assert final_response.json()["amount_paid"] == "100.00"


async def test_overpayment_is_rejected(client: AsyncClient, fake_verifier, db_session) -> None:
    """ADR-0007: 'Overpayment beyond the total is rejected with a 409.'"""
    actor = await login_as(client, fake_verifier, db_session, role=Role.OWNER)
    client_row = await make_client(db_session, organization=actor.organization)
    invoice = await _make_sent_invoice(
        db_session,
        organization=actor.organization,
        client_row=client_row,
        created_by=actor.membership,
    )
    await db_session.commit()

    response = await client.post(
        f"/api/v1/finance/invoices/{invoice.id}/payments",
        json={"amount": "150.00", "paid_on": "2026-02-01", "method": "cash"},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == 409


async def test_overpayment_via_second_payment_is_rejected(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.OWNER)
    client_row = await make_client(db_session, organization=actor.organization)
    invoice = await _make_sent_invoice(
        db_session,
        organization=actor.organization,
        client_row=client_row,
        created_by=actor.membership,
    )
    await db_session.commit()

    first = await client.post(
        f"/api/v1/finance/invoices/{invoice.id}/payments",
        json={"amount": "80.00", "paid_on": "2026-02-01", "method": "cash"},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert first.status_code == 201

    second = await client.post(
        f"/api/v1/finance/invoices/{invoice.id}/payments",
        json={"amount": "30.00", "paid_on": "2026-02-02", "method": "cash"},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert second.status_code == 409

    invoice_response = await client.get(f"/api/v1/finance/invoices/{invoice.id}")
    assert invoice_response.json()["amount_paid"] == "80.00"
    assert invoice_response.json()["status"] == "PARTIALLY_PAID"


async def test_payment_rejects_non_positive_amount(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.OWNER)
    client_row = await make_client(db_session, organization=actor.organization)
    invoice = await _make_sent_invoice(
        db_session,
        organization=actor.organization,
        client_row=client_row,
        created_by=actor.membership,
    )
    await db_session.commit()

    response = await client.post(
        f"/api/v1/finance/invoices/{invoice.id}/payments",
        json={"amount": "0.00", "paid_on": "2026-02-01", "method": "cash"},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == 422


@pytest.mark.parametrize("status", [InvoiceStatus.DRAFT, InvoiceStatus.CANCELLED])
async def test_payment_against_non_payable_status_is_rejected(
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
        f"/api/v1/finance/invoices/{invoice.id}/payments",
        json={"amount": "10.00", "paid_on": "2026-02-01", "method": "cash"},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == 409


async def test_payment_against_already_paid_invoice_is_rejected(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.OWNER)
    client_row = await make_client(db_session, organization=actor.organization)
    invoice = await make_invoice(
        db_session,
        organization=actor.organization,
        client=client_row,
        created_by=actor.membership,
        status=InvoiceStatus.PAID,
    )
    await db_session.commit()

    response = await client.post(
        f"/api/v1/finance/invoices/{invoice.id}/payments",
        json={"amount": "10.00", "paid_on": "2026-02-01", "method": "cash"},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == 409


async def test_admin_can_list_payments(client: AsyncClient, fake_verifier, db_session) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.ADMIN)
    client_row = await make_client(db_session, organization=actor.organization)
    invoice = await _make_sent_invoice(
        db_session,
        organization=actor.organization,
        client_row=client_row,
        created_by=actor.membership,
    )
    await db_session.commit()

    await client.post(
        f"/api/v1/finance/invoices/{invoice.id}/payments",
        json={"amount": "25.00", "paid_on": "2026-02-01", "method": "cash"},
        headers={"X-CSRF-Token": actor.csrf_token},
    )

    response = await client.get(f"/api/v1/finance/invoices/{invoice.id}/payments")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["amount"] == "25.00"


async def test_payment_routes_in_another_org_are_404(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    other_org = await make_organization(db_session)
    other_owner = await make_user(db_session, email=f"pay-other-{other_org.id}@x.com")
    other_actor = await make_membership(
        db_session, organization=other_org, user=other_owner, role=Role.OWNER
    )
    other_client = await make_client(db_session, organization=other_org)
    other_invoice = await make_invoice(
        db_session,
        organization=other_org,
        client=other_client,
        created_by=other_actor,
        status=InvoiceStatus.SENT,
    )
    await db_session.commit()

    actor = await login_as(client, fake_verifier, db_session, role=Role.ADMIN)

    post_response = await client.post(
        f"/api/v1/finance/invoices/{other_invoice.id}/payments",
        json={"amount": "10.00", "paid_on": "2026-02-01", "method": "cash"},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert post_response.status_code == 404

    get_response = await client.get(f"/api/v1/finance/invoices/{other_invoice.id}/payments")
    assert get_response.status_code == 404


async def test_concurrent_payments_only_one_can_push_over_the_limit() -> None:
    """ADR-0007: 'Concurrent-payment tests are required to prove that two
    requests cannot both pass the balance check against the same prior
    amount.' Needs two genuinely independent DB connections, not two
    SAVEPOINTs sharing one transaction — same approach and reason as
    test_lead_conversion.py's own concurrent-conversion race test and
    test_invoices.py's own concurrent-send/-cancel tests. Real commits, no
    test fixtures — cleaned up explicitly at the end following that
    test's own FULL FK-ordered cleanup, not just the activity_events part.

    A SENT $100 invoice, two concurrent $60 payments: only one may
    succeed (60 <= 100, but 60+60=120 > 100) — proves the balance check
    can't pass twice against the same stale prior amount."""
    session_factory = get_session_factory()

    setup_session = session_factory()
    try:
        org = await make_organization(setup_session)
        owner_user = await make_user(setup_session, email=f"owner-{org.id}@x.com")
        owner = await make_membership(
            setup_session, organization=org, user=owner_user, role=Role.OWNER
        )
        client_row = await make_client(setup_session, organization=org)
        invoice = await make_invoice(
            setup_session,
            organization=org,
            client=client_row,
            created_by=owner,
            subtotal=Decimal("100.00"),
            status=InvoiceStatus.SENT,
        )
        await setup_session.commit()
        org_id, owner_id, invoice_id = org.id, owner.id, invoice.id
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

        results = await asyncio.gather(
            record_payment(
                session_1,
                organization_id=org_id,
                actor=actor_1,
                invoice_id=invoice_id,
                amount=Decimal("60.00"),
                currency="USD",
                paid_on=date(2026, 2, 1),
                method="cash",
                reference=None,
            ),
            record_payment(
                session_2,
                organization_id=org_id,
                actor=actor_2,
                invoice_id=invoice_id,
                amount=Decimal("60.00"),
                currency="USD",
                paid_on=date(2026, 2, 1),
                method="cash",
                reference=None,
            ),
            return_exceptions=True,
        )

        successes = [r for r in results if not isinstance(r, Exception)]
        failures = [r for r in results if isinstance(r, Exception)]
        assert len(successes) == 1, f"expected exactly one success, got: {results}"
        assert len(failures) == 1
        assert isinstance(failures[0], ConflictError)

        # The invoice's own amount_paid must reflect exactly the one
        # payment that won, never both (a lost-update race would show
        # 60.00 too, so this alone isn't sufficient — the real proof is
        # the assertions above: only one call succeeded at all).
        verify_session = session_factory()
        try:
            invoice_row = (
                await verify_session.execute(
                    select(Invoice).where(
                        Invoice.organization_id == org_id, Invoice.id == invoice_id
                    )
                )
            ).scalar_one()
            assert invoice_row.amount_paid == Decimal("60.00")
            assert invoice_row.status == InvoiceStatus.PARTIALLY_PAID
        finally:
            await verify_session.close()
    finally:
        await session_1.close()
        await session_2.close()

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

        cleanup_session = session_factory()
        try:
            await cleanup_session.execute(delete(Payment).where(Payment.organization_id == org_id))
            await cleanup_session.execute(
                delete(InvoiceItem).where(InvoiceItem.organization_id == org_id)
            )
            await cleanup_session.execute(delete(Invoice).where(Invoice.organization_id == org_id))
            await cleanup_session.execute(delete(Client).where(Client.organization_id == org_id))
            await cleanup_session.execute(
                delete(Membership).where(Membership.organization_id == org_id)
            )
            await cleanup_session.execute(delete(User).where(User.id == owner_user_id))
            await cleanup_session.execute(delete(Organization).where(Organization.id == org_id))
            await cleanup_session.commit()
        finally:
            await cleanup_session.close()

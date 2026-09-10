from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.factories import make_client, make_income, make_membership, make_organization, make_user
from tests.helpers import login_as
from trinol.core.authz.permissions import Role

pytestmark = pytest.mark.usefixtures("db_session")


@pytest.mark.parametrize("role", [Role.ADMIN, Role.OWNER])
async def test_admin_and_up_can_create_income(
    client: AsyncClient, fake_verifier, db_session, role: Role
) -> None:
    """RBAC.md §2: "Income/expenses: write" is ADMIN+-tier only."""
    actor = await login_as(client, fake_verifier, db_session, role=role)
    response = await client.post(
        "/api/v1/finance/income",
        json={
            "amount": "1500.00",
            "source": "Consulting retainer",
            "received_on": "2026-09-01",
            "payment_method": "bank_transfer",
        },
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["amount"] == "1500.00"
    assert body["currency"] == "USD"
    assert body["source"] == "Consulting retainer"
    assert body["received_on"] == "2026-09-01"


@pytest.mark.parametrize("role", [Role.MEMBER, Role.MANAGER])
async def test_member_and_manager_cannot_create_income(
    client: AsyncClient, fake_verifier, db_session, role: Role
) -> None:
    """RBAC.md §3: finance is invisible to MEMBER and MANAGER, not just
    ADMIN-tier-and-below CRM/work modules."""
    actor = await login_as(client, fake_verifier, db_session, role=role)
    response = await client.post(
        "/api/v1/finance/income",
        json={
            "amount": "100.00",
            "source": "Test",
            "received_on": "2026-09-01",
            "payment_method": "cash",
        },
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == 403


@pytest.mark.parametrize("role", [Role.MEMBER, Role.MANAGER])
async def test_member_and_manager_cannot_list_income(
    client: AsyncClient, fake_verifier, db_session, role: Role
) -> None:
    await login_as(client, fake_verifier, db_session, role=role)
    response = await client.get("/api/v1/finance/income")
    assert response.status_code == 403


async def test_create_income_rejects_non_positive_amount(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.OWNER)
    response = await client.post(
        "/api/v1/finance/income",
        json={
            "amount": "0.00",
            "source": "Test",
            "received_on": "2026-09-01",
            "payment_method": "cash",
        },
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == 422


async def test_create_income_rejects_client_not_in_organization(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.OWNER)
    other_org = await make_organization(db_session)
    other_client = await make_client(db_session, organization=other_org)
    await db_session.commit()

    response = await client.post(
        "/api/v1/finance/income",
        json={
            "amount": "100.00",
            "source": "Test",
            "received_on": "2026-09-01",
            "payment_method": "cash",
            "client_id": str(other_client.id),
        },
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == 404


async def test_admin_can_list_and_get_income(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.ADMIN)
    seeded = await make_income(
        db_session,
        organization=actor.organization,
        created_by=actor.membership,
        source="Seeded income",
    )
    await db_session.commit()

    list_response = await client.get("/api/v1/finance/income")
    assert list_response.status_code == 200
    assert any(item["id"] == str(seeded.id) for item in list_response.json()["items"])

    get_response = await client.get(f"/api/v1/finance/income/{seeded.id}")
    assert get_response.status_code == 200
    assert get_response.json()["source"] == "Seeded income"


async def test_update_income_partial_fields(client: AsyncClient, fake_verifier, db_session) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.OWNER)
    create_response = await client.post(
        "/api/v1/finance/income",
        json={
            "amount": "200.00",
            "source": "Original source",
            "received_on": "2026-09-01",
            "payment_method": "cash",
        },
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    income_id = create_response.json()["id"]

    response = await client.patch(
        f"/api/v1/finance/income/{income_id}",
        json={"notes": "Reconciled"},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["notes"] == "Reconciled"
    assert body["source"] == "Original source"


async def test_update_income_rejects_non_positive_amount(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.OWNER)
    create_response = await client.post(
        "/api/v1/finance/income",
        json={
            "amount": "200.00",
            "source": "Original source",
            "received_on": "2026-09-01",
            "payment_method": "cash",
        },
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    income_id = create_response.json()["id"]

    response = await client.patch(
        f"/api/v1/finance/income/{income_id}",
        json={"amount": "-5.00"},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == 422


async def test_admin_can_delete_income(client: AsyncClient, fake_verifier, db_session) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.ADMIN)
    create_response = await client.post(
        "/api/v1/finance/income",
        json={
            "amount": "50.00",
            "source": "To delete",
            "received_on": "2026-09-01",
            "payment_method": "cash",
        },
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    income_id = create_response.json()["id"]

    delete_response = await client.delete(
        f"/api/v1/finance/income/{income_id}", headers={"X-CSRF-Token": actor.csrf_token}
    )
    assert delete_response.status_code == 204

    get_response = await client.get(f"/api/v1/finance/income/{income_id}")
    assert get_response.status_code == 404


async def test_income_in_another_org_is_404(client: AsyncClient, fake_verifier, db_session) -> None:
    other_org = await make_organization(db_session)
    other_owner = await make_user(db_session, email=f"owner-{other_org.id}@x.com")
    other_actor = await make_membership(
        db_session, organization=other_org, user=other_owner, role=Role.OWNER
    )
    other_income = await make_income(
        db_session, organization=other_org, created_by=other_actor, source="Other org income"
    )
    await db_session.commit()

    actor = await login_as(client, fake_verifier, db_session, role=Role.ADMIN)

    get_response = await client.get(f"/api/v1/finance/income/{other_income.id}")
    assert get_response.status_code == 404

    patch_response = await client.patch(
        f"/api/v1/finance/income/{other_income.id}",
        json={"notes": "hijack"},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert patch_response.status_code == 404

    delete_response = await client.delete(
        f"/api/v1/finance/income/{other_income.id}", headers={"X-CSRF-Token": actor.csrf_token}
    )
    assert delete_response.status_code == 404

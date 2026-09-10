from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.factories import (
    PNG_1X1_BYTES,
    make_expense,
    make_membership,
    make_organization,
    make_user,
)
from tests.helpers import login_as
from trinol.core.authz.permissions import Role
from trinol.main import app
from trinol.platform.file_storage.deps import get_file_storage
from trinol.platform.file_storage.local import LocalFileStorage

pytestmark = pytest.mark.usefixtures("db_session")


@pytest.fixture
def local_storage(tmp_path):
    storage = LocalFileStorage(tmp_path)
    app.dependency_overrides[get_file_storage] = lambda: storage
    try:
        yield storage
    finally:
        app.dependency_overrides.pop(get_file_storage, None)


@pytest.mark.parametrize("role", [Role.ADMIN, Role.OWNER])
async def test_admin_and_up_can_create_expense(
    client: AsyncClient, fake_verifier, db_session, role: Role
) -> None:
    """RBAC.md §2: "Income/expenses: write" is ADMIN+-tier only."""
    actor = await login_as(client, fake_verifier, db_session, role=role)
    response = await client.post(
        "/api/v1/finance/expenses",
        json={
            "amount": "49.99",
            "category": "SOFTWARE",
            "description": "Design tool subscription",
            "spent_on": "2026-09-01",
            "payment_method": "card",
        },
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["amount"] == "49.99"
    assert body["category"] == "SOFTWARE"
    assert body["receipt_file_id"] is None


@pytest.mark.parametrize("role", [Role.MEMBER, Role.MANAGER])
async def test_member_and_manager_cannot_create_expense(
    client: AsyncClient, fake_verifier, db_session, role: Role
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=role)
    response = await client.post(
        "/api/v1/finance/expenses",
        json={
            "amount": "10.00",
            "category": "OTHER",
            "description": "Test",
            "spent_on": "2026-09-01",
            "payment_method": "cash",
        },
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == 403


async def test_create_expense_rejects_non_positive_amount(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.OWNER)
    response = await client.post(
        "/api/v1/finance/expenses",
        json={
            "amount": "0.00",
            "category": "OTHER",
            "description": "Test",
            "spent_on": "2026-09-01",
            "payment_method": "cash",
        },
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == 422


@pytest.mark.parametrize(
    "field", ["amount", "currency", "category", "description", "spent_on", "payment_method"]
)
async def test_patch_rejects_null_for_required_fields(
    client: AsyncClient, fake_verifier, db_session, field: str
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.OWNER)
    create_response = await client.post(
        "/api/v1/finance/expenses",
        json={
            "amount": "100.00",
            "category": "HOSTING",
            "description": "Server bill",
            "spent_on": "2026-09-01",
            "payment_method": "card",
        },
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    expense_id = create_response.json()["id"]

    response = await client.patch(
        f"/api/v1/finance/expenses/{expense_id}",
        json={field: None},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == 422


async def test_admin_can_list_and_get_expense(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.ADMIN)
    seeded = await make_expense(
        db_session,
        organization=actor.organization,
        created_by=actor.membership,
        description="Seeded expense",
    )
    await db_session.commit()

    list_response = await client.get("/api/v1/finance/expenses")
    assert list_response.status_code == 200
    assert any(item["id"] == str(seeded.id) for item in list_response.json()["items"])

    get_response = await client.get(f"/api/v1/finance/expenses/{seeded.id}")
    assert get_response.status_code == 200
    assert get_response.json()["description"] == "Seeded expense"


async def test_update_expense_partial_fields(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.OWNER)
    create_response = await client.post(
        "/api/v1/finance/expenses",
        json={
            "amount": "20.00",
            "category": "TRAVEL",
            "description": "Taxi",
            "spent_on": "2026-09-01",
            "payment_method": "cash",
        },
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    expense_id = create_response.json()["id"]

    response = await client.patch(
        f"/api/v1/finance/expenses/{expense_id}",
        json={"notes": "Client site visit"},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["notes"] == "Client site visit"
    assert body["description"] == "Taxi"


async def test_upload_then_download_receipt(
    client: AsyncClient, fake_verifier, db_session, local_storage
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.ADMIN)
    create_response = await client.post(
        "/api/v1/finance/expenses",
        json={
            "amount": "49.99",
            "category": "SOFTWARE",
            "description": "Subscription",
            "spent_on": "2026-09-01",
            "payment_method": "card",
        },
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    expense_id = create_response.json()["id"]

    upload_response = await client.post(
        f"/api/v1/finance/expenses/{expense_id}/receipt",
        files={"file": ("receipt.png", PNG_1X1_BYTES, "image/png")},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert upload_response.status_code == 201
    assert upload_response.json()["receipt_file_id"] is not None

    download_response = await client.get(f"/api/v1/finance/expenses/{expense_id}/receipt")
    assert download_response.status_code == 200
    assert download_response.content == PNG_1X1_BYTES
    assert download_response.headers["content-type"] == "image/png"
    assert download_response.headers["x-content-type-options"] == "nosniff"


async def test_uploading_a_second_receipt_replaces_and_deletes_the_first_blob(
    client: AsyncClient, fake_verifier, db_session, local_storage, tmp_path
) -> None:
    """A 1:1 receipt, not a list — re-uploading must not leave the first
    blob orphaned on disk (ADR-0008)."""
    actor = await login_as(client, fake_verifier, db_session, role=Role.ADMIN)
    create_response = await client.post(
        "/api/v1/finance/expenses",
        json={
            "amount": "49.99",
            "category": "SOFTWARE",
            "description": "Subscription",
            "spent_on": "2026-09-01",
            "payment_method": "card",
        },
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    expense_id = create_response.json()["id"]

    first_upload = await client.post(
        f"/api/v1/finance/expenses/{expense_id}/receipt",
        files={"file": ("first.png", PNG_1X1_BYTES, "image/png")},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    first_file_id = first_upload.json()["receipt_file_id"]
    assert len([f for f in tmp_path.rglob("*") if f.is_file()]) == 1

    second_upload = await client.post(
        f"/api/v1/finance/expenses/{expense_id}/receipt",
        files={"file": ("second.png", PNG_1X1_BYTES, "image/png")},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert second_upload.status_code == 201
    second_file_id = second_upload.json()["receipt_file_id"]
    assert second_file_id != first_file_id
    # Exactly one blob remains — the first was deleted, not left orphaned.
    assert len([f for f in tmp_path.rglob("*") if f.is_file()]) == 1

    download_response = await client.get(f"/api/v1/finance/expenses/{expense_id}/receipt")
    assert download_response.status_code == 200


async def test_delete_receipt_removes_row_and_blob(
    client: AsyncClient, fake_verifier, db_session, local_storage, tmp_path
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.ADMIN)
    create_response = await client.post(
        "/api/v1/finance/expenses",
        json={
            "amount": "49.99",
            "category": "SOFTWARE",
            "description": "Subscription",
            "spent_on": "2026-09-01",
            "payment_method": "card",
        },
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    expense_id = create_response.json()["id"]
    await client.post(
        f"/api/v1/finance/expenses/{expense_id}/receipt",
        files={"file": ("receipt.png", PNG_1X1_BYTES, "image/png")},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert any(f.is_file() for f in tmp_path.rglob("*"))

    delete_response = await client.delete(
        f"/api/v1/finance/expenses/{expense_id}/receipt",
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert delete_response.status_code == 204
    assert not any(f.is_file() for f in tmp_path.rglob("*"))

    get_response = await client.get(f"/api/v1/finance/expenses/{expense_id}")
    assert get_response.json()["receipt_file_id"] is None

    download_response = await client.get(f"/api/v1/finance/expenses/{expense_id}/receipt")
    assert download_response.status_code == 404


async def test_delete_expense_with_receipt_cleans_up_blob(
    client: AsyncClient, fake_verifier, db_session, local_storage, tmp_path
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.ADMIN)
    create_response = await client.post(
        "/api/v1/finance/expenses",
        json={
            "amount": "49.99",
            "category": "SOFTWARE",
            "description": "Subscription",
            "spent_on": "2026-09-01",
            "payment_method": "card",
        },
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    expense_id = create_response.json()["id"]
    await client.post(
        f"/api/v1/finance/expenses/{expense_id}/receipt",
        files={"file": ("receipt.png", PNG_1X1_BYTES, "image/png")},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert any(f.is_file() for f in tmp_path.rglob("*"))

    delete_response = await client.delete(
        f"/api/v1/finance/expenses/{expense_id}",
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert delete_response.status_code == 204
    assert not any(f.is_file() for f in tmp_path.rglob("*"))

    get_response = await client.get(f"/api/v1/finance/expenses/{expense_id}")
    assert get_response.status_code == 404


async def test_expense_in_another_org_is_404(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    other_org = await make_organization(db_session)
    other_owner = await make_user(db_session, email=f"owner-{other_org.id}@x.com")
    other_actor = await make_membership(
        db_session, organization=other_org, user=other_owner, role=Role.OWNER
    )
    other_expense = await make_expense(
        db_session, organization=other_org, created_by=other_actor, description="Other org expense"
    )
    await db_session.commit()

    actor = await login_as(client, fake_verifier, db_session, role=Role.ADMIN)

    get_response = await client.get(f"/api/v1/finance/expenses/{other_expense.id}")
    assert get_response.status_code == 404

    patch_response = await client.patch(
        f"/api/v1/finance/expenses/{other_expense.id}",
        json={"notes": "hijack"},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert patch_response.status_code == 404

    delete_response = await client.delete(
        f"/api/v1/finance/expenses/{other_expense.id}", headers={"X-CSRF-Token": actor.csrf_token}
    )
    assert delete_response.status_code == 404

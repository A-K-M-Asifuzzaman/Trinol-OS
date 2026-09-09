from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.factories import make_membership, make_organization, make_user
from tests.helpers import login_as
from trinol.core.authz.permissions import Role
from trinol.modules.crm.models import ClientStatus
from trinol.modules.crm.services.client_service import create_client

pytestmark = pytest.mark.usefixtures("db_session")


@pytest.mark.parametrize("role", [Role.MANAGER, Role.ADMIN, Role.OWNER])
async def test_manager_and_up_can_create_client(
    client: AsyncClient, fake_verifier, db_session, role: Role
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=role)
    response = await client.post(
        "/api/v1/clients",
        json={"name": "Acme Corp", "company": "Acme", "email": "hello@acme.test"},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Acme Corp"
    assert body["company"] == "Acme"
    assert body["status"] == "ACTIVE"
    assert body["owner_id"] is None
    assert body["archived_at"] is None


async def test_member_cannot_create_client(client: AsyncClient, fake_verifier, db_session) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.MEMBER)
    response = await client.post(
        "/api/v1/clients",
        json={"name": "Acme Corp"},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == 403


async def test_create_client_rejects_owner_not_in_organization(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.ADMIN)
    other_org = await make_organization(db_session)
    outsider = await make_user(db_session, email=f"outsider-{other_org.id}@x.com")
    await make_membership(db_session, organization=other_org, user=outsider, role=Role.MEMBER)
    await db_session.commit()

    response = await client.post(
        "/api/v1/clients",
        json={"name": "Acme Corp", "owner_id": str(outsider.id)},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == 400


@pytest.mark.parametrize("role", [Role.MEMBER, Role.MANAGER, Role.ADMIN, Role.OWNER])
async def test_every_role_can_list_and_get_clients(
    client: AsyncClient, fake_verifier, db_session, role: Role
) -> None:
    """RBAC.md §2: "Leads & clients: view" is open to every role."""
    actor = await login_as(client, fake_verifier, db_session, role=role)
    owner = await make_user(db_session, email=f"client-owner-{actor.organization.id}@x.com")
    owner_membership = await make_membership(
        db_session, organization=actor.organization, user=owner, role=Role.OWNER
    )
    await db_session.commit()
    seeded = await create_client(
        db_session,
        organization_id=actor.organization.id,
        actor=owner_membership,
        name="Acme Corp",
        company=None,
        email=None,
        phone=None,
        website=None,
        address=None,
        notes=None,
        status=ClientStatus.ACTIVE,
        owner_id=None,
    )

    list_response = await client.get("/api/v1/clients")
    assert list_response.status_code == 200
    assert any(item["id"] == str(seeded.id) for item in list_response.json()["items"])

    get_response = await client.get(f"/api/v1/clients/{seeded.id}")
    assert get_response.status_code == 200
    assert get_response.json()["name"] == "Acme Corp"


async def test_list_clients_excludes_archived(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.OWNER)
    create_response = await client.post(
        "/api/v1/clients",
        json={"name": "Acme Corp"},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    client_id = create_response.json()["id"]

    delete_response = await client.delete(
        f"/api/v1/clients/{client_id}", headers={"X-CSRF-Token": actor.csrf_token}
    )
    assert delete_response.status_code == 200
    assert delete_response.json()["archived_at"] is not None

    list_response = await client.get("/api/v1/clients")
    assert list_response.status_code == 200
    assert all(item["id"] != client_id for item in list_response.json()["items"])


async def test_manager_can_archive_a_client(client: AsyncClient, fake_verifier, db_session) -> None:
    """Unlike projects (PROJECT_DELETE, ADMIN+-only), clients have no
    distinct delete permission — archive reuses CLIENT_WRITE (MANAGER+),
    ROADMAP.md's stated Phase 3 assumption."""
    actor = await login_as(client, fake_verifier, db_session, role=Role.MANAGER)
    create_response = await client.post(
        "/api/v1/clients",
        json={"name": "Acme Corp"},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    client_id = create_response.json()["id"]

    response = await client.delete(
        f"/api/v1/clients/{client_id}", headers={"X-CSRF-Token": actor.csrf_token}
    )
    assert response.status_code == 200


async def test_update_client_partial_fields(client: AsyncClient, fake_verifier, db_session) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.OWNER)
    create_response = await client.post(
        "/api/v1/clients",
        json={"name": "Acme Corp", "company": "Acme"},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    client_id = create_response.json()["id"]

    response = await client.patch(
        f"/api/v1/clients/{client_id}",
        json={"notes": "Key account"},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["notes"] == "Key account"
    assert body["name"] == "Acme Corp"
    assert body["company"] == "Acme"


@pytest.mark.parametrize("field", ["name", "status"])
async def test_patch_rejects_null_for_required_fields(
    client: AsyncClient, fake_verifier, db_session, field: str
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.OWNER)
    create_response = await client.post(
        "/api/v1/clients",
        json={"name": "Acme Corp"},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    client_id = create_response.json()["id"]

    response = await client.patch(
        f"/api/v1/clients/{client_id}",
        json={field: None},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == 422


async def test_client_in_another_org_is_404(client: AsyncClient, fake_verifier, db_session) -> None:
    other_org = await make_organization(db_session)
    other_owner = await make_user(db_session, email=f"owner-{other_org.id}@x.com")
    other_actor = await make_membership(
        db_session, organization=other_org, user=other_owner, role=Role.OWNER
    )
    await db_session.commit()

    other_client = await create_client(
        db_session,
        organization_id=other_org.id,
        actor=other_actor,
        name="Other Org Client",
        company=None,
        email=None,
        phone=None,
        website=None,
        address=None,
        notes=None,
        status=ClientStatus.ACTIVE,
        owner_id=None,
    )

    actor = await login_as(client, fake_verifier, db_session, role=Role.ADMIN)

    get_response = await client.get(f"/api/v1/clients/{other_client.id}")
    assert get_response.status_code == 404

    patch_response = await client.patch(
        f"/api/v1/clients/{other_client.id}",
        json={"notes": "hijack"},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert patch_response.status_code == 404

    delete_response = await client.delete(
        f"/api/v1/clients/{other_client.id}", headers={"X-CSRF-Token": actor.csrf_token}
    )
    assert delete_response.status_code == 404

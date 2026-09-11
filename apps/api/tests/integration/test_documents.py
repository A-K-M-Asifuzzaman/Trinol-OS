from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.factories import (
    make_client,
    make_document_reference,
    make_meeting,
    make_membership,
    make_organization,
    make_project,
    make_user,
)
from tests.helpers import login_as
from trinol.core.authz.permissions import Role

pytestmark = pytest.mark.usefixtures("db_session")


@pytest.mark.parametrize("role", [Role.MANAGER, Role.ADMIN, Role.OWNER])
async def test_manager_and_up_can_create_document_reference(
    client: AsyncClient, fake_verifier, db_session, role: Role
) -> None:
    """RBAC.md §2: "Documents: create/edit/delete" is MANAGER+-tier."""
    actor = await login_as(client, fake_verifier, db_session, role=role)
    response = await client.post(
        "/api/v1/documents",
        json={
            "title": "Requirements doc",
            "url": "https://drive.google.com/test",
            "kind": "GOOGLE_DRIVE",
        },
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["title"] == "Requirements doc"
    assert body["kind"] == "GOOGLE_DRIVE"
    assert body["project_id"] is None


async def test_member_cannot_create_document_reference(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    """RBAC.md §2: MEMBER may view but not write."""
    actor = await login_as(client, fake_verifier, db_session, role=Role.MEMBER)
    response = await client.post(
        "/api/v1/documents",
        json={"title": "Test", "url": "https://example.test", "kind": "OTHER"},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == 403


async def test_member_can_list_document_references(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.MEMBER)
    seeded = await make_document_reference(
        db_session, organization=actor.organization, added_by=actor.membership
    )
    await db_session.commit()

    response = await client.get("/api/v1/documents")
    assert response.status_code == 200
    assert any(item["id"] == str(seeded.id) for item in response.json()["items"])


async def test_create_document_reference_rejects_project_not_in_organization(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.OWNER)
    other_org = await make_organization(db_session)
    other_owner_user = await make_user(db_session, email=f"other-owner-{other_org.id}@x.com")
    other_owner = await make_membership(
        db_session, organization=other_org, user=other_owner_user, role=Role.OWNER
    )
    other_project = await make_project(db_session, organization=other_org, owner=other_owner)
    await db_session.commit()

    response = await client.post(
        "/api/v1/documents",
        json={
            "title": "Test",
            "url": "https://example.test",
            "kind": "OTHER",
            "project_id": str(other_project.id),
        },
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == 404


async def test_create_document_reference_with_client_and_meeting_links(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    """Phase 6 plan decision 4: a reference may have more than one parent
    set simultaneously — no CHECK constraint forces exactly one."""
    actor = await login_as(client, fake_verifier, db_session, role=Role.OWNER)
    client_row = await make_client(
        db_session, organization=actor.organization, owner=actor.membership
    )
    meeting = await make_meeting(
        db_session, organization=actor.organization, created_by=actor.membership
    )
    await db_session.commit()

    response = await client.post(
        "/api/v1/documents",
        json={
            "title": "Signed contract",
            "url": "https://example.test/contract",
            "kind": "OTHER",
            "client_id": str(client_row.id),
            "meeting_id": str(meeting.id),
        },
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["client_id"] == str(client_row.id)
    assert body["meeting_id"] == str(meeting.id)


async def test_owner_can_list_and_get_document_reference(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.OWNER)
    seeded = await make_document_reference(
        db_session,
        organization=actor.organization,
        added_by=actor.membership,
        title="Seeded doc",
    )
    await db_session.commit()

    list_response = await client.get("/api/v1/documents")
    assert list_response.status_code == 200
    assert any(item["id"] == str(seeded.id) for item in list_response.json()["items"])

    get_response = await client.get(f"/api/v1/documents/{seeded.id}")
    assert get_response.status_code == 200
    assert get_response.json()["title"] == "Seeded doc"


async def test_update_document_reference_partial_fields(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.MANAGER)
    create_response = await client.post(
        "/api/v1/documents",
        json={"title": "Original title", "url": "https://example.test", "kind": "OTHER"},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    document_id = create_response.json()["id"]

    response = await client.patch(
        f"/api/v1/documents/{document_id}",
        json={"title": "Updated title"},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "Updated title"
    assert body["url"] == "https://example.test"


@pytest.mark.parametrize("field", ["title", "url", "kind"])
async def test_patch_rejects_null_for_required_fields(
    client: AsyncClient, fake_verifier, db_session, field: str
) -> None:
    """Same class of Codex finding as IncomeUpdateRequest (Phase 5): an
    explicit `null` for a NOT NULL column must be a clean 422, not an
    unhandled 500."""
    actor = await login_as(client, fake_verifier, db_session, role=Role.OWNER)
    create_response = await client.post(
        "/api/v1/documents",
        json={"title": "Original title", "url": "https://example.test", "kind": "OTHER"},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    document_id = create_response.json()["id"]

    response = await client.patch(
        f"/api/v1/documents/{document_id}",
        json={field: None},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == 422


async def test_owner_can_delete_document_reference(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.OWNER)
    create_response = await client.post(
        "/api/v1/documents",
        json={"title": "To delete", "url": "https://example.test", "kind": "OTHER"},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    document_id = create_response.json()["id"]

    delete_response = await client.delete(
        f"/api/v1/documents/{document_id}", headers={"X-CSRF-Token": actor.csrf_token}
    )
    assert delete_response.status_code == 204

    get_response = await client.get(f"/api/v1/documents/{document_id}")
    assert get_response.status_code == 404


async def test_document_reference_in_another_org_is_404(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    other_org = await make_organization(db_session)
    other_owner_user = await make_user(db_session, email=f"owner-{other_org.id}@x.com")
    other_actor = await make_membership(
        db_session, organization=other_org, user=other_owner_user, role=Role.OWNER
    )
    other_document = await make_document_reference(
        db_session, organization=other_org, added_by=other_actor, title="Other org doc"
    )
    await db_session.commit()

    actor = await login_as(client, fake_verifier, db_session, role=Role.OWNER)

    get_response = await client.get(f"/api/v1/documents/{other_document.id}")
    assert get_response.status_code == 404

    patch_response = await client.patch(
        f"/api/v1/documents/{other_document.id}",
        json={"title": "hijack"},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert patch_response.status_code == 404

    delete_response = await client.delete(
        f"/api/v1/documents/{other_document.id}", headers={"X-CSRF-Token": actor.csrf_token}
    )
    assert delete_response.status_code == 404

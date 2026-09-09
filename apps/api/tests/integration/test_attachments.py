from __future__ import annotations

import hashlib

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from tests.factories import (
    PNG_1X1_BYTES,
    make_membership,
    make_organization,
    make_task,
    make_task_attachment,
    make_user,
)
from tests.helpers import login_as
from trinol.core.authz.permissions import Role
from trinol.main import app
from trinol.platform.activity import list_audit
from trinol.platform.file_storage.deps import get_file_storage
from trinol.platform.file_storage.local import LocalFileStorage
from trinol.platform.models import FileObject

pytestmark = pytest.mark.usefixtures("db_session")


@pytest.fixture
def local_storage(tmp_path):
    storage = LocalFileStorage(tmp_path)
    app.dependency_overrides[get_file_storage] = lambda: storage
    try:
        yield storage
    finally:
        app.dependency_overrides.pop(get_file_storage, None)


async def test_upload_then_download_round_trips_bytes_and_checksum(
    client: AsyncClient, fake_verifier, db_session, local_storage
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.MEMBER)
    task_response = await client.post(
        "/api/v1/tasks", json={"title": "Task"}, headers={"X-CSRF-Token": actor.csrf_token}
    )
    task_id = task_response.json()["id"]

    upload_response = await client.post(
        f"/api/v1/tasks/{task_id}/attachments",
        files={"file": ("receipt.png", PNG_1X1_BYTES, "image/png")},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert upload_response.status_code == 201
    body = upload_response.json()
    assert body["filename"] == "receipt.png"
    assert body["content_type"] == "image/png"
    assert body["size_bytes"] == len(PNG_1X1_BYTES)
    attachment_id = body["id"]

    download_response = await client.get(
        f"/api/v1/tasks/{task_id}/attachments/{attachment_id}/download"
    )
    assert download_response.status_code == 200
    assert download_response.content == PNG_1X1_BYTES
    assert (
        hashlib.sha256(download_response.content).hexdigest()
        == hashlib.sha256(PNG_1X1_BYTES).hexdigest()
    )
    assert download_response.headers["content-type"] == "image/png"
    assert 'attachment; filename="receipt.png"' in download_response.headers["content-disposition"]
    assert download_response.headers["x-content-type-options"] == "nosniff"


async def test_list_attachments(
    client: AsyncClient, fake_verifier, db_session, local_storage
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.MEMBER)
    task_response = await client.post(
        "/api/v1/tasks", json={"title": "Task"}, headers={"X-CSRF-Token": actor.csrf_token}
    )
    task_id = task_response.json()["id"]
    await client.post(
        f"/api/v1/tasks/{task_id}/attachments",
        files={"file": ("receipt.png", PNG_1X1_BYTES, "image/png")},
        headers={"X-CSRF-Token": actor.csrf_token},
    )

    response = await client.get(f"/api/v1/tasks/{task_id}/attachments")
    assert response.status_code == 200
    assert [a["filename"] for a in response.json()["items"]] == ["receipt.png"]


async def test_renamed_exe_with_image_extension_is_rejected(
    client: AsyncClient, fake_verifier, db_session, local_storage
) -> None:
    """SECURITY.md §6: sniffed content type, not the client's claimed one
    — an executable's magic bytes (MZ header) don't match any allowed
    signature, so it's rejected regardless of its .png extension."""
    actor = await login_as(client, fake_verifier, db_session, role=Role.MEMBER)
    task_response = await client.post(
        "/api/v1/tasks", json={"title": "Task"}, headers={"X-CSRF-Token": actor.csrf_token}
    )
    task_id = task_response.json()["id"]

    fake_exe = b"MZ" + b"\x00" * 100
    response = await client.post(
        f"/api/v1/tasks/{task_id}/attachments",
        files={"file": ("totally-an-image.png", fake_exe, "image/png")},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == 422


async def test_pdf_renamed_to_png_extension_is_rejected(
    client: AsyncClient, fake_verifier, db_session, local_storage
) -> None:
    """A *real* file signature, just the wrong one for its claimed
    extension — distinct from the previous test (no signature at all)."""
    actor = await login_as(client, fake_verifier, db_session, role=Role.MEMBER)
    task_response = await client.post(
        "/api/v1/tasks", json={"title": "Task"}, headers={"X-CSRF-Token": actor.csrf_token}
    )
    task_id = task_response.json()["id"]

    fake_pdf_as_png = b"%PDF-1.4\n" + b"\x00" * 100
    response = await client.post(
        f"/api/v1/tasks/{task_id}/attachments",
        files={"file": ("document.png", fake_pdf_as_png, "image/png")},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == 422


async def test_svg_upload_is_rejected(
    client: AsyncClient, fake_verifier, db_session, local_storage
) -> None:
    """SECURITY.md §6: "SVG uploads are rejected... (scriptable)" — no
    special-case code, just the general extension-allowlist mechanism."""
    actor = await login_as(client, fake_verifier, db_session, role=Role.MEMBER)
    task_response = await client.post(
        "/api/v1/tasks", json={"title": "Task"}, headers={"X-CSRF-Token": actor.csrf_token}
    )
    task_id = task_response.json()["id"]

    response = await client.post(
        f"/api/v1/tasks/{task_id}/attachments",
        files={"file": ("image.svg", b"<svg></svg>", "image/svg+xml")},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == 422


async def test_oversized_upload_is_rejected(
    client: AsyncClient, fake_verifier, db_session, local_storage
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.MEMBER)
    task_response = await client.post(
        "/api/v1/tasks", json={"title": "Task"}, headers={"X-CSRF-Token": actor.csrf_token}
    )
    task_id = task_response.json()["id"]

    oversized = b"\x89PNG\r\n\x1a\n" + b"\x00" * (10 * 1024 * 1024 + 1)
    response = await client.post(
        f"/api/v1/tasks/{task_id}/attachments",
        files={"file": ("big.png", oversized, "image/png")},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == 422


async def test_delete_attachment_removes_row_and_blob_and_is_audited(
    client: AsyncClient, fake_verifier, db_session, local_storage, tmp_path
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.MEMBER)
    task_response = await client.post(
        "/api/v1/tasks", json={"title": "Task"}, headers={"X-CSRF-Token": actor.csrf_token}
    )
    task_id = task_response.json()["id"]
    upload_response = await client.post(
        f"/api/v1/tasks/{task_id}/attachments",
        files={"file": ("receipt.png", PNG_1X1_BYTES, "image/png")},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    attachment_id = upload_response.json()["id"]
    # ADR-0008: "deleting a database row must also delete the object" —
    # confirmed on the actual filesystem, not just inferred from the DB
    # row/download 404s below (a download 404s on a missing *row* too,
    # which wouldn't by itself prove the blob was ever touched).
    stored_files_before = list(tmp_path.rglob("*"))
    assert any(f.is_file() for f in stored_files_before)

    response = await client.delete(
        f"/api/v1/tasks/{task_id}/attachments/{attachment_id}",
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == 204

    assert not any(f.is_file() for f in tmp_path.rglob("*"))

    list_response = await client.get(f"/api/v1/tasks/{task_id}/attachments")
    assert list_response.json()["items"] == []

    download_response = await client.get(
        f"/api/v1/tasks/{task_id}/attachments/{attachment_id}/download"
    )
    assert download_response.status_code == 404

    audit_rows = await list_audit(db_session, organization_id=actor.organization.id)
    deleted_events = [row for row in audit_rows if row.event == "task_attachment.deleted"]
    assert len(deleted_events) == 1
    assert str(deleted_events[0].entity_id) == attachment_id


async def test_deleting_task_cleans_up_attachment_rows_and_blobs(
    client: AsyncClient, fake_verifier, db_session, local_storage, tmp_path
) -> None:
    """ADR-0008: deleting a database row must also delete the object.
    `task_attachments` cascades away at the DB level (ADR-0011), but
    `file_objects` doesn't hang off `tasks` in the FK graph, so it (and the
    blob it names) would otherwise be silently orphaned on every task
    delete that had attachments. Checked directly against the database and
    the filesystem, not just inferred from the task's own 404 — that alone
    wouldn't distinguish "cleaned up properly" from "orphaned but
    unreachable through this task_id"."""
    actor = await login_as(client, fake_verifier, db_session, role=Role.MEMBER)
    task_response = await client.post(
        "/api/v1/tasks", json={"title": "Task"}, headers={"X-CSRF-Token": actor.csrf_token}
    )
    task_id = task_response.json()["id"]
    upload_response = await client.post(
        f"/api/v1/tasks/{task_id}/attachments",
        files={"file": ("receipt.png", PNG_1X1_BYTES, "image/png")},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    file_id = upload_response.json()["file_id"]
    assert any(f.is_file() for f in tmp_path.rglob("*"))

    delete_response = await client.delete(
        f"/api/v1/tasks/{task_id}", headers={"X-CSRF-Token": actor.csrf_token}
    )
    assert delete_response.status_code == 204

    get_response = await client.get(f"/api/v1/tasks/{task_id}")
    assert get_response.status_code == 404

    file_object_result = await db_session.execute(
        select(FileObject).where(
            FileObject.organization_id == actor.organization.id, FileObject.id == file_id
        )
    )
    assert file_object_result.scalar_one_or_none() is None
    assert not any(f.is_file() for f in tmp_path.rglob("*"))


async def test_attachment_on_task_in_another_org_is_404(
    client: AsyncClient, fake_verifier, db_session, local_storage
) -> None:
    other_org = await make_organization(db_session)
    other_user = await make_user(db_session, email=f"other-{other_org.id}@x.com")
    other_membership = await make_membership(
        db_session, organization=other_org, user=other_user, role=Role.MEMBER
    )
    other_task = await make_task(db_session, organization=other_org, created_by=other_membership)
    other_attachment = await make_task_attachment(
        db_session, task=other_task, uploaded_by=other_membership, storage=local_storage
    )
    await db_session.commit()

    actor = await login_as(client, fake_verifier, db_session, role=Role.ADMIN)
    list_response = await client.get(f"/api/v1/tasks/{other_task.id}/attachments")
    assert list_response.status_code == 404

    download_response = await client.get(
        f"/api/v1/tasks/{other_task.id}/attachments/{other_attachment.id}/download"
    )
    assert download_response.status_code == 404
    assert actor.csrf_token  # sanity: logged in as expected

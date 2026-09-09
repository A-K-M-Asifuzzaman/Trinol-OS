from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient

from tests.factories import (
    make_client,
    make_meeting,
    make_meeting_participant,
    make_membership,
    make_organization,
    make_project,
    make_user,
)
from tests.helpers import login_as, login_as_existing
from trinol.core.authz.permissions import Role
from trinol.platform.activity import list_audit, list_feed

pytestmark = pytest.mark.usefixtures("db_session")


def _times() -> tuple[str, str]:
    starts = datetime.now(UTC) + timedelta(days=1)
    ends = starts + timedelta(hours=1)
    return starts.isoformat(), ends.isoformat()


@pytest.mark.parametrize("role", list(Role))
async def test_every_role_can_create_a_meeting(
    client: AsyncClient, fake_verifier, db_session, role: Role
) -> None:
    """RBAC.md §2: "Meetings: create/edit own" is granted to every role —
    no ownership check on create, there's no prior resource to own yet."""
    actor = await login_as(client, fake_verifier, db_session, role=role)
    starts_at, ends_at = _times()
    response = await client.post(
        "/api/v1/meetings",
        json={"title": "Kickoff", "starts_at": starts_at, "ends_at": ends_at},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["title"] == "Kickoff"
    assert body["created_by"] == str(actor.membership.user_id)


async def test_create_meeting_rejects_ends_at_not_after_starts_at(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.MEMBER)
    starts_at, ends_at = _times()
    response = await client.post(
        "/api/v1/meetings",
        # Swapped: ends before starts.
        json={"title": "Bad Times", "starts_at": ends_at, "ends_at": starts_at},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == 422


async def test_create_meeting_with_client_and_project_links(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.MANAGER)
    client_row = await make_client(db_session, organization=actor.organization)
    project = await make_project(
        db_session, organization=actor.organization, owner=actor.membership
    )
    await db_session.commit()
    starts_at, ends_at = _times()

    response = await client.post(
        "/api/v1/meetings",
        json={
            "title": "Client Sync",
            "starts_at": starts_at,
            "ends_at": ends_at,
            "client_id": str(client_row.id),
            "project_id": str(project.id),
        },
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["client_id"] == str(client_row.id)
    assert body["project_id"] == str(project.id)


async def test_create_meeting_rejects_client_from_another_org(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.MANAGER)
    other_org = await make_organization(db_session)
    other_client = await make_client(db_session, organization=other_org)
    await db_session.commit()
    starts_at, ends_at = _times()

    response = await client.post(
        "/api/v1/meetings",
        json={
            "title": "Cross-org Client",
            "starts_at": starts_at,
            "ends_at": ends_at,
            "client_id": str(other_client.id),
        },
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == 404


async def test_creator_can_get_own_meeting(client: AsyncClient, fake_verifier, db_session) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.MEMBER)
    meeting = await make_meeting(
        db_session, organization=actor.organization, created_by=actor.membership
    )
    await db_session.commit()

    response = await client.get(f"/api/v1/meetings/{meeting.id}")
    assert response.status_code == 200
    assert response.json()["id"] == str(meeting.id)


async def test_participant_can_get_meeting_they_did_not_create(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    creator_actor = await login_as(client, fake_verifier, db_session, role=Role.MEMBER)
    meeting = await make_meeting(
        db_session, organization=creator_actor.organization, created_by=creator_actor.membership
    )
    participant_user = await make_user(
        db_session, email=f"participant-{creator_actor.organization.id}@x.com"
    )
    participant_membership = await make_membership(
        db_session, organization=creator_actor.organization, user=participant_user, role=Role.MEMBER
    )
    await make_meeting_participant(db_session, meeting=meeting, user=participant_membership)
    await db_session.commit()

    await login_as_existing(
        client,
        fake_verifier,
        user=participant_user,
        membership=participant_membership,
        organization=creator_actor.organization,
    )
    response = await client.get(f"/api/v1/meetings/{meeting.id}")
    assert response.status_code == 200


async def test_non_participant_member_gets_403_on_detail(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    creator_actor = await login_as(client, fake_verifier, db_session, role=Role.MEMBER)
    meeting = await make_meeting(
        db_session, organization=creator_actor.organization, created_by=creator_actor.membership
    )
    outsider_user = await make_user(
        db_session, email=f"outsider-{creator_actor.organization.id}@x.com"
    )
    outsider_membership = await make_membership(
        db_session, organization=creator_actor.organization, user=outsider_user, role=Role.MEMBER
    )
    await db_session.commit()

    await login_as_existing(
        client,
        fake_verifier,
        user=outsider_user,
        membership=outsider_membership,
        organization=creator_actor.organization,
    )
    response = await client.get(f"/api/v1/meetings/{meeting.id}")
    assert response.status_code == 403


@pytest.mark.parametrize("role", [Role.MANAGER, Role.ADMIN, Role.OWNER])
async def test_manager_and_up_can_view_a_meeting_they_did_not_create(
    client: AsyncClient, fake_verifier, db_session, role: Role
) -> None:
    creator_actor = await login_as(client, fake_verifier, db_session, role=Role.MEMBER)
    meeting = await make_meeting(
        db_session, organization=creator_actor.organization, created_by=creator_actor.membership
    )
    manager_user = await make_user(
        db_session, email=f"manager-{creator_actor.organization.id}@x.com"
    )
    manager_membership = await make_membership(
        db_session, organization=creator_actor.organization, user=manager_user, role=role
    )
    await db_session.commit()

    await login_as_existing(
        client,
        fake_verifier,
        user=manager_user,
        membership=manager_membership,
        organization=creator_actor.organization,
    )
    response = await client.get(f"/api/v1/meetings/{meeting.id}")
    assert response.status_code == 200


async def test_list_meetings_hides_meetings_a_member_cannot_see(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    creator_actor = await login_as(client, fake_verifier, db_session, role=Role.MEMBER)
    visible = await make_meeting(
        db_session,
        organization=creator_actor.organization,
        created_by=creator_actor.membership,
        title="Visible",
    )
    hidden = await make_meeting(
        db_session,
        organization=creator_actor.organization,
        created_by=creator_actor.membership,
        title="Hidden",
    )

    outsider_user = await make_user(
        db_session, email=f"list-outsider-{creator_actor.organization.id}@x.com"
    )
    outsider_membership = await make_membership(
        db_session, organization=creator_actor.organization, user=outsider_user, role=Role.MEMBER
    )
    await make_meeting_participant(db_session, meeting=visible, user=outsider_membership)
    await db_session.commit()

    await login_as_existing(
        client,
        fake_verifier,
        user=outsider_user,
        membership=outsider_membership,
        organization=creator_actor.organization,
    )
    response = await client.get("/api/v1/meetings")
    assert response.status_code == 200
    titles = {item["title"] for item in response.json()["items"]}
    assert titles == {"Visible"}
    assert hidden.id  # sanity: hidden meeting really exists, just not listed


async def test_creator_can_update_own_meeting(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.MEMBER)
    meeting = await make_meeting(
        db_session, organization=actor.organization, created_by=actor.membership
    )
    await db_session.commit()

    response = await client.patch(
        f"/api/v1/meetings/{meeting.id}",
        json={"title": "Renamed"},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == 200
    assert response.json()["title"] == "Renamed"


async def test_non_creator_member_cannot_update_meeting(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    creator_actor = await login_as(client, fake_verifier, db_session, role=Role.MEMBER)
    meeting = await make_meeting(
        db_session, organization=creator_actor.organization, created_by=creator_actor.membership
    )
    outsider_user = await make_user(
        db_session, email=f"patch-outsider-{creator_actor.organization.id}@x.com"
    )
    outsider_membership = await make_membership(
        db_session, organization=creator_actor.organization, user=outsider_user, role=Role.MEMBER
    )
    await make_meeting_participant(db_session, meeting=meeting, user=outsider_membership)
    await db_session.commit()

    outsider = await login_as_existing(
        client,
        fake_verifier,
        user=outsider_user,
        membership=outsider_membership,
        organization=creator_actor.organization,
    )
    response = await client.patch(
        f"/api/v1/meetings/{meeting.id}",
        json={"title": "Hijacked"},
        headers={"X-CSRF-Token": outsider.csrf_token},
    )
    assert response.status_code == 403


@pytest.mark.parametrize("role", [Role.MANAGER, Role.ADMIN, Role.OWNER])
async def test_manager_and_up_can_update_a_meeting_they_did_not_create(
    client: AsyncClient, fake_verifier, db_session, role: Role
) -> None:
    creator_actor = await login_as(client, fake_verifier, db_session, role=Role.MEMBER)
    meeting = await make_meeting(
        db_session, organization=creator_actor.organization, created_by=creator_actor.membership
    )
    manager_user = await make_user(
        db_session, email=f"patch-manager-{creator_actor.organization.id}@x.com"
    )
    manager_membership = await make_membership(
        db_session, organization=creator_actor.organization, user=manager_user, role=role
    )
    await db_session.commit()

    manager = await login_as_existing(
        client,
        fake_verifier,
        user=manager_user,
        membership=manager_membership,
        organization=creator_actor.organization,
    )
    response = await client.patch(
        f"/api/v1/meetings/{meeting.id}",
        json={"title": "Manager Renamed"},
        headers={"X-CSRF-Token": manager.csrf_token},
    )
    assert response.status_code == 200


async def test_update_meeting_rejects_ends_at_before_persisted_starts_at(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    """Partial update: only ends_at is sent, so the cross-field check must
    compare against the persisted starts_at, not just within the request
    body (same reasoning as update_project's start_date/deadline split)."""
    actor = await login_as(client, fake_verifier, db_session, role=Role.MEMBER)
    starts_at, ends_at = _times()
    meeting = await make_meeting(
        db_session,
        organization=actor.organization,
        created_by=actor.membership,
        starts_at=datetime.fromisoformat(starts_at),
        ends_at=datetime.fromisoformat(ends_at),
    )
    await db_session.commit()

    earlier_than_starts = (datetime.fromisoformat(starts_at) - timedelta(hours=1)).isoformat()
    response = await client.patch(
        f"/api/v1/meetings/{meeting.id}",
        json={"ends_at": earlier_than_starts},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == 422


async def test_creator_can_delete_own_meeting(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.MEMBER)
    meeting = await make_meeting(
        db_session, organization=actor.organization, created_by=actor.membership
    )
    await db_session.commit()

    response = await client.delete(
        f"/api/v1/meetings/{meeting.id}", headers={"X-CSRF-Token": actor.csrf_token}
    )
    assert response.status_code == 204

    get_response = await client.get(f"/api/v1/meetings/{meeting.id}")
    assert get_response.status_code == 404


async def test_non_creator_member_cannot_delete_meeting(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    creator_actor = await login_as(client, fake_verifier, db_session, role=Role.MEMBER)
    meeting = await make_meeting(
        db_session, organization=creator_actor.organization, created_by=creator_actor.membership
    )
    outsider_user = await make_user(
        db_session, email=f"delete-outsider-{creator_actor.organization.id}@x.com"
    )
    outsider_membership = await make_membership(
        db_session, organization=creator_actor.organization, user=outsider_user, role=Role.MEMBER
    )
    await db_session.commit()

    outsider = await login_as_existing(
        client,
        fake_verifier,
        user=outsider_user,
        membership=outsider_membership,
        organization=creator_actor.organization,
    )
    response = await client.delete(
        f"/api/v1/meetings/{meeting.id}", headers={"X-CSRF-Token": outsider.csrf_token}
    )
    assert response.status_code == 403


async def test_delete_meeting_records_audit_event_not_feed_event(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    """ADR-0011: meetings are hard-deleted — the audit event is the only
    remaining record of who deleted it and when."""
    actor = await login_as(client, fake_verifier, db_session, role=Role.MEMBER)
    meeting = await make_meeting(
        db_session, organization=actor.organization, created_by=actor.membership
    )
    await db_session.commit()
    meeting_id = meeting.id

    response = await client.delete(
        f"/api/v1/meetings/{meeting_id}", headers={"X-CSRF-Token": actor.csrf_token}
    )
    assert response.status_code == 204

    audit_rows = await list_audit(db_session, organization_id=actor.organization.id)
    deleted_events = [e for e in audit_rows if e.entity_id == meeting_id]
    assert len(deleted_events) == 1
    assert deleted_events[0].event == "meeting.deleted"

    feed_rows = await list_feed(db_session, organization_id=actor.organization.id)
    assert all(e.entity_id != meeting_id or e.event != "meeting.deleted" for e in feed_rows)


async def test_create_meeting_records_feed_event_not_audit_event(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.MEMBER)
    starts_at, ends_at = _times()
    response = await client.post(
        "/api/v1/meetings",
        json={"title": "Feed Check", "starts_at": starts_at, "ends_at": ends_at},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == 201
    meeting_id = response.json()["id"]

    feed_rows = await list_feed(db_session, organization_id=actor.organization.id)
    created_events = [e for e in feed_rows if str(e.entity_id) == meeting_id]
    assert len(created_events) == 1
    assert created_events[0].event == "meeting.created"


async def test_get_meeting_in_another_org_is_404(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    other_org = await make_organization(db_session)
    other_owner_user = await make_user(db_session, email=f"meeting-owner-{other_org.id}@x.com")
    other_owner_membership = await make_membership(
        db_session, organization=other_org, user=other_owner_user, role=Role.OWNER
    )
    other_meeting = await make_meeting(
        db_session, organization=other_org, created_by=other_owner_membership
    )
    await db_session.commit()

    await login_as(client, fake_verifier, db_session, role=Role.ADMIN)
    response = await client.get(f"/api/v1/meetings/{other_meeting.id}")
    assert response.status_code == 404

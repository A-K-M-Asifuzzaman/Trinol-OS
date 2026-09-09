from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.factories import (
    make_meeting,
    make_meeting_participant,
    make_membership,
    make_organization,
    make_user,
)
from tests.helpers import login_as, login_as_existing
from trinol.core.authz.permissions import Role
from trinol.platform.activity import list_audit, list_feed

# RBAC.md §3 'Meeting edit' governs add/remove (creator or MANAGER+, no new
# permission needed — MEETING_WRITE_OWN is already MEMBER-tier reachability).
# Updating your OWN response is a narrow exception: allowed regardless of
# can_write_meeting (Phase 4 Stage 1 decision).

pytestmark = pytest.mark.usefixtures("db_session")


async def test_creator_can_add_a_participant_by_user_id(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.MEMBER)
    meeting = await make_meeting(
        db_session, organization=actor.organization, created_by=actor.membership
    )
    invitee_user = await make_user(db_session, email=f"invitee-{actor.organization.id}@x.com")
    await make_membership(
        db_session, organization=actor.organization, user=invitee_user, role=Role.MEMBER
    )
    await db_session.commit()

    response = await client.post(
        f"/api/v1/meetings/{meeting.id}/participants",
        json={"user_id": str(invitee_user.id)},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["user_id"] == str(invitee_user.id)
    assert body["external_email"] is None
    assert body["response"] == "PENDING"


async def test_creator_can_add_a_participant_by_external_email(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.MEMBER)
    meeting = await make_meeting(
        db_session, organization=actor.organization, created_by=actor.membership
    )
    await db_session.commit()

    response = await client.post(
        f"/api/v1/meetings/{meeting.id}/participants",
        json={"external_email": "guest@example.test"},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["external_email"] == "guest@example.test"
    assert body["user_id"] is None


async def test_add_participant_rejects_both_user_id_and_external_email(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.MEMBER)
    meeting = await make_meeting(
        db_session, organization=actor.organization, created_by=actor.membership
    )
    await db_session.commit()

    response = await client.post(
        f"/api/v1/meetings/{meeting.id}/participants",
        json={"user_id": str(actor.membership.user_id), "external_email": "guest@example.test"},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == 422


async def test_add_participant_rejects_neither_user_id_nor_external_email(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.MEMBER)
    meeting = await make_meeting(
        db_session, organization=actor.organization, created_by=actor.membership
    )
    await db_session.commit()

    response = await client.post(
        f"/api/v1/meetings/{meeting.id}/participants",
        json={},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == 422


async def test_add_participant_rejects_duplicate_user(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.MEMBER)
    meeting = await make_meeting(
        db_session, organization=actor.organization, created_by=actor.membership
    )
    invitee_user = await make_user(db_session, email=f"dup-{actor.organization.id}@x.com")
    invitee_membership = await make_membership(
        db_session, organization=actor.organization, user=invitee_user, role=Role.MEMBER
    )
    await make_meeting_participant(db_session, meeting=meeting, user=invitee_membership)
    await db_session.commit()

    response = await client.post(
        f"/api/v1/meetings/{meeting.id}/participants",
        json={"user_id": str(invitee_user.id)},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == 409


async def test_non_creator_member_cannot_add_a_participant(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    creator_actor = await login_as(client, fake_verifier, db_session, role=Role.MEMBER)
    meeting = await make_meeting(
        db_session, organization=creator_actor.organization, created_by=creator_actor.membership
    )
    outsider_user = await make_user(
        db_session, email=f"add-outsider-{creator_actor.organization.id}@x.com"
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
    response = await client.post(
        f"/api/v1/meetings/{meeting.id}/participants",
        json={"external_email": "guest@example.test"},
        headers={"X-CSRF-Token": outsider.csrf_token},
    )
    assert response.status_code == 403


@pytest.mark.parametrize("role", [Role.MANAGER, Role.ADMIN, Role.OWNER])
async def test_manager_and_up_can_add_a_participant_to_a_meeting_they_did_not_create(
    client: AsyncClient, fake_verifier, db_session, role: Role
) -> None:
    creator_actor = await login_as(client, fake_verifier, db_session, role=Role.MEMBER)
    meeting = await make_meeting(
        db_session, organization=creator_actor.organization, created_by=creator_actor.membership
    )
    manager_user = await make_user(
        db_session, email=f"add-manager-{creator_actor.organization.id}@x.com"
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
    response = await client.post(
        f"/api/v1/meetings/{meeting.id}/participants",
        json={"external_email": "guest@example.test"},
        headers={"X-CSRF-Token": manager.csrf_token},
    )
    assert response.status_code == 201


async def test_add_participant_records_audit_event_not_feed_event(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.MEMBER)
    meeting = await make_meeting(
        db_session, organization=actor.organization, created_by=actor.membership
    )
    await db_session.commit()

    response = await client.post(
        f"/api/v1/meetings/{meeting.id}/participants",
        json={"external_email": "guest@example.test"},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == 201
    participant_id = response.json()["id"]

    audit_rows = await list_audit(db_session, organization_id=actor.organization.id)
    added_events = [e for e in audit_rows if str(e.entity_id) == participant_id]
    assert len(added_events) == 1
    assert added_events[0].event == "meeting_participant.added"

    feed_rows = await list_feed(db_session, organization_id=actor.organization.id)
    assert all(str(e.entity_id) != participant_id for e in feed_rows)


async def test_adding_a_participant_grants_them_visibility(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    org = await make_organization(db_session)
    creator_user = await make_user(db_session, email=f"visibility-creator-{org.id}@x.com")
    creator_membership = await make_membership(
        db_session, organization=org, user=creator_user, role=Role.MEMBER
    )
    meeting = await make_meeting(db_session, organization=org, created_by=creator_membership)
    invitee_user = await make_user(db_session, email=f"visibility-invitee-{org.id}@x.com")
    invitee_membership = await make_membership(
        db_session, organization=org, user=invitee_user, role=Role.MEMBER
    )
    await db_session.commit()

    await login_as_existing(
        client, fake_verifier, user=invitee_user, membership=invitee_membership, organization=org
    )
    before = await client.get(f"/api/v1/meetings/{meeting.id}")
    assert before.status_code == 403

    creator = await login_as_existing(
        client, fake_verifier, user=creator_user, membership=creator_membership, organization=org
    )
    add_response = await client.post(
        f"/api/v1/meetings/{meeting.id}/participants",
        json={"user_id": str(invitee_user.id)},
        headers={"X-CSRF-Token": creator.csrf_token},
    )
    assert add_response.status_code == 201

    await login_as_existing(
        client, fake_verifier, user=invitee_user, membership=invitee_membership, organization=org
    )
    after = await client.get(f"/api/v1/meetings/{meeting.id}")
    assert after.status_code == 200


async def test_creator_can_remove_a_participant(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.MEMBER)
    meeting = await make_meeting(
        db_session, organization=actor.organization, created_by=actor.membership
    )
    invitee_user = await make_user(db_session, email=f"remove-{actor.organization.id}@x.com")
    invitee_membership = await make_membership(
        db_session, organization=actor.organization, user=invitee_user, role=Role.MEMBER
    )
    participant = await make_meeting_participant(
        db_session, meeting=meeting, user=invitee_membership
    )
    await db_session.commit()

    response = await client.delete(
        f"/api/v1/meetings/{meeting.id}/participants/{participant.id}",
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == 204


async def test_non_creator_member_cannot_remove_a_participant(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    creator_actor = await login_as(client, fake_verifier, db_session, role=Role.MEMBER)
    meeting = await make_meeting(
        db_session, organization=creator_actor.organization, created_by=creator_actor.membership
    )
    invitee_user = await make_user(
        db_session, email=f"remove-target-{creator_actor.organization.id}@x.com"
    )
    invitee_membership = await make_membership(
        db_session, organization=creator_actor.organization, user=invitee_user, role=Role.MEMBER
    )
    participant = await make_meeting_participant(
        db_session, meeting=meeting, user=invitee_membership
    )

    outsider_user = await make_user(
        db_session, email=f"remove-outsider-{creator_actor.organization.id}@x.com"
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
        f"/api/v1/meetings/{meeting.id}/participants/{participant.id}",
        headers={"X-CSRF-Token": outsider.csrf_token},
    )
    assert response.status_code == 403


async def test_participant_can_update_their_own_response(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    creator_actor = await login_as(client, fake_verifier, db_session, role=Role.MEMBER)
    meeting = await make_meeting(
        db_session, organization=creator_actor.organization, created_by=creator_actor.membership
    )
    invitee_user = await make_user(
        db_session, email=f"own-response-{creator_actor.organization.id}@x.com"
    )
    invitee_membership = await make_membership(
        db_session, organization=creator_actor.organization, user=invitee_user, role=Role.MEMBER
    )
    participant = await make_meeting_participant(
        db_session, meeting=meeting, user=invitee_membership
    )
    await db_session.commit()

    invitee = await login_as_existing(
        client,
        fake_verifier,
        user=invitee_user,
        membership=invitee_membership,
        organization=creator_actor.organization,
    )
    response = await client.patch(
        f"/api/v1/meetings/{meeting.id}/participants/{participant.id}",
        json={"response": "ACCEPTED"},
        headers={"X-CSRF-Token": invitee.csrf_token},
    )
    assert response.status_code == 200
    assert response.json()["response"] == "ACCEPTED"


async def test_non_creator_member_cannot_update_someone_elses_response(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    creator_actor = await login_as(client, fake_verifier, db_session, role=Role.MEMBER)
    meeting = await make_meeting(
        db_session, organization=creator_actor.organization, created_by=creator_actor.membership
    )
    invitee_user = await make_user(
        db_session, email=f"other-response-{creator_actor.organization.id}@x.com"
    )
    invitee_membership = await make_membership(
        db_session, organization=creator_actor.organization, user=invitee_user, role=Role.MEMBER
    )
    participant = await make_meeting_participant(
        db_session, meeting=meeting, user=invitee_membership
    )

    outsider_user = await make_user(
        db_session, email=f"patch-outsider-{creator_actor.organization.id}@x.com"
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
    response = await client.patch(
        f"/api/v1/meetings/{meeting.id}/participants/{participant.id}",
        json={"response": "DECLINED"},
        headers={"X-CSRF-Token": outsider.csrf_token},
    )
    assert response.status_code == 403


async def test_creator_can_update_a_participants_response_on_their_behalf(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    """can_write_meeting (creator or MANAGER+) is also allowed to set a
    participant's response, distinct from that participant's own
    self-service exception."""
    actor = await login_as(client, fake_verifier, db_session, role=Role.MEMBER)
    meeting = await make_meeting(
        db_session, organization=actor.organization, created_by=actor.membership
    )
    invitee_user = await make_user(db_session, email=f"onbehalf-{actor.organization.id}@x.com")
    invitee_membership = await make_membership(
        db_session, organization=actor.organization, user=invitee_user, role=Role.MEMBER
    )
    participant = await make_meeting_participant(
        db_session, meeting=meeting, user=invitee_membership
    )
    await db_session.commit()

    response = await client.patch(
        f"/api/v1/meetings/{meeting.id}/participants/{participant.id}",
        json={"response": "TENTATIVE"},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == 200
    assert response.json()["response"] == "TENTATIVE"


async def test_list_participants_visible_to_anyone_who_can_see_the_meeting(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    creator_actor = await login_as(client, fake_verifier, db_session, role=Role.MEMBER)
    meeting = await make_meeting(
        db_session, organization=creator_actor.organization, created_by=creator_actor.membership
    )
    invitee_user = await make_user(db_session, email=f"list-{creator_actor.organization.id}@x.com")
    invitee_membership = await make_membership(
        db_session, organization=creator_actor.organization, user=invitee_user, role=Role.MEMBER
    )
    await make_meeting_participant(db_session, meeting=meeting, user=invitee_membership)
    await db_session.commit()

    response = await client.get(f"/api/v1/meetings/{meeting.id}/participants")
    assert response.status_code == 200
    assert response.json()["total"] == 1


async def test_get_participant_in_another_org_meeting_is_404(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    other_org = await make_organization(db_session)
    other_owner_user = await make_user(db_session, email=f"other-owner-{other_org.id}@x.com")
    other_owner_membership = await make_membership(
        db_session, organization=other_org, user=other_owner_user, role=Role.OWNER
    )
    other_meeting = await make_meeting(
        db_session, organization=other_org, created_by=other_owner_membership
    )
    await db_session.commit()

    await login_as(client, fake_verifier, db_session, role=Role.ADMIN)
    response = await client.get(f"/api/v1/meetings/{other_meeting.id}/participants")
    assert response.status_code == 404

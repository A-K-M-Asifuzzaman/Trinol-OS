from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.factories import make_meeting, make_membership, make_organization, make_user
from tests.helpers import login_as, login_as_existing
from trinol.core.authz.permissions import Role
from trinol.platform.activity import list_audit, list_feed

# Decisions inherit the meeting's own edit rule (creator or MANAGER+), not
# an author-only rule — no independent permission, no PATCH (append-only in
# spirit, no edited_at in DATABASE.md's spec).

pytestmark = pytest.mark.usefixtures("db_session")


async def test_creator_can_record_a_decision(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.MEMBER)
    meeting = await make_meeting(
        db_session, organization=actor.organization, created_by=actor.membership
    )
    await db_session.commit()

    response = await client.post(
        f"/api/v1/meetings/{meeting.id}/decisions",
        json={"body": "We will use Postgres."},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["body"] == "We will use Postgres."
    assert body["decided_by"] == str(actor.membership.user_id)


async def test_non_creator_member_cannot_record_a_decision(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    creator_actor = await login_as(client, fake_verifier, db_session, role=Role.MEMBER)
    meeting = await make_meeting(
        db_session, organization=creator_actor.organization, created_by=creator_actor.membership
    )
    outsider_user = await make_user(
        db_session, email=f"decision-outsider-{creator_actor.organization.id}@x.com"
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
        f"/api/v1/meetings/{meeting.id}/decisions",
        json={"body": "Hijack"},
        headers={"X-CSRF-Token": outsider.csrf_token},
    )
    assert response.status_code == 403


@pytest.mark.parametrize("role", [Role.MANAGER, Role.ADMIN, Role.OWNER])
async def test_manager_and_up_can_record_a_decision_for_a_meeting_they_did_not_create(
    client: AsyncClient, fake_verifier, db_session, role: Role
) -> None:
    creator_actor = await login_as(client, fake_verifier, db_session, role=Role.MEMBER)
    meeting = await make_meeting(
        db_session, organization=creator_actor.organization, created_by=creator_actor.membership
    )
    manager_user = await make_user(
        db_session, email=f"decision-manager-{creator_actor.organization.id}@x.com"
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
        f"/api/v1/meetings/{meeting.id}/decisions",
        json={"body": "Approved."},
        headers={"X-CSRF-Token": manager.csrf_token},
    )
    assert response.status_code == 201


async def test_create_decision_records_feed_event_not_audit_event(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.MEMBER)
    meeting = await make_meeting(
        db_session, organization=actor.organization, created_by=actor.membership
    )
    await db_session.commit()

    response = await client.post(
        f"/api/v1/meetings/{meeting.id}/decisions",
        json={"body": "Feed check."},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == 201
    decision_id = response.json()["id"]

    feed_rows = await list_feed(db_session, organization_id=actor.organization.id)
    created_events = [e for e in feed_rows if str(e.entity_id) == decision_id]
    assert len(created_events) == 1
    assert created_events[0].event == "meeting_decision.created"


async def test_list_decisions_visible_to_anyone_who_can_see_the_meeting(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.MEMBER)
    meeting = await make_meeting(
        db_session, organization=actor.organization, created_by=actor.membership
    )
    await db_session.commit()
    await client.post(
        f"/api/v1/meetings/{meeting.id}/decisions",
        json={"body": "One."},
        headers={"X-CSRF-Token": actor.csrf_token},
    )

    response = await client.get(f"/api/v1/meetings/{meeting.id}/decisions")
    assert response.status_code == 200
    assert response.json()["total"] == 1


async def test_creator_can_delete_a_decision(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.MEMBER)
    meeting = await make_meeting(
        db_session, organization=actor.organization, created_by=actor.membership
    )
    await db_session.commit()
    create_response = await client.post(
        f"/api/v1/meetings/{meeting.id}/decisions",
        json={"body": "Delete me."},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    decision_id = create_response.json()["id"]

    response = await client.delete(
        f"/api/v1/meetings/{meeting.id}/decisions/{decision_id}",
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == 204


async def test_delete_decision_records_audit_event_per_adr_0011(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.MEMBER)
    meeting = await make_meeting(
        db_session, organization=actor.organization, created_by=actor.membership
    )
    await db_session.commit()
    create_response = await client.post(
        f"/api/v1/meetings/{meeting.id}/decisions",
        json={"body": "Delete me."},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    decision_id = create_response.json()["id"]

    await client.delete(
        f"/api/v1/meetings/{meeting.id}/decisions/{decision_id}",
        headers={"X-CSRF-Token": actor.csrf_token},
    )

    audit_rows = await list_audit(db_session, organization_id=actor.organization.id)
    deleted_events = [e for e in audit_rows if str(e.entity_id) == decision_id]
    assert len(deleted_events) == 1
    assert deleted_events[0].event == "meeting_decision.deleted"


async def test_non_creator_member_cannot_delete_a_decision(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    creator_actor = await login_as(client, fake_verifier, db_session, role=Role.MEMBER)
    meeting = await make_meeting(
        db_session, organization=creator_actor.organization, created_by=creator_actor.membership
    )
    await db_session.commit()
    create_response = await client.post(
        f"/api/v1/meetings/{meeting.id}/decisions",
        json={"body": "Keep me."},
        headers={"X-CSRF-Token": creator_actor.csrf_token},
    )
    decision_id = create_response.json()["id"]

    outsider_user = await make_user(
        db_session, email=f"decision-delete-outsider-{creator_actor.organization.id}@x.com"
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
        f"/api/v1/meetings/{meeting.id}/decisions/{decision_id}",
        headers={"X-CSRF-Token": outsider.csrf_token},
    )
    assert response.status_code == 403


async def test_get_decision_in_another_org_meeting_is_404(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    other_org = await make_organization(db_session)
    other_owner_user = await make_user(db_session, email=f"decision-other-{other_org.id}@x.com")
    other_owner_membership = await make_membership(
        db_session, organization=other_org, user=other_owner_user, role=Role.OWNER
    )
    other_meeting = await make_meeting(
        db_session, organization=other_org, created_by=other_owner_membership
    )
    await db_session.commit()

    await login_as(client, fake_verifier, db_session, role=Role.ADMIN)
    response = await client.get(f"/api/v1/meetings/{other_meeting.id}/decisions")
    assert response.status_code == 404

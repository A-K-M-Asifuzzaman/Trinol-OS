from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.factories import make_meeting, make_membership, make_organization, make_user
from tests.helpers import login_as, login_as_existing
from trinol.core.authz.permissions import Role
from trinol.platform.activity import list_audit, list_feed

# Actions inherit the meeting's own edit rule (creator or MANAGER+), same
# reasoning as decisions — no independent permission. Unlike decisions,
# actions support PATCH (owner_id/description/due_date only — task_id is
# never client-settable, it's set exactly once by promote_action in Stage 5).

pytestmark = pytest.mark.usefixtures("db_session")


async def test_creator_can_add_an_action_item(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.MEMBER)
    meeting = await make_meeting(
        db_session, organization=actor.organization, created_by=actor.membership
    )
    await db_session.commit()

    response = await client.post(
        f"/api/v1/meetings/{meeting.id}/actions",
        json={"description": "Send the proposal."},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["description"] == "Send the proposal."
    assert body["task_id"] is None


async def test_create_action_with_owner_and_due_date(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.MANAGER)
    meeting = await make_meeting(
        db_session, organization=actor.organization, created_by=actor.membership
    )
    owner_user = await make_user(db_session, email=f"action-owner-{actor.organization.id}@x.com")
    owner_membership = await make_membership(
        db_session, organization=actor.organization, user=owner_user, role=Role.MEMBER
    )
    await db_session.commit()

    response = await client.post(
        f"/api/v1/meetings/{meeting.id}/actions",
        json={
            "description": "Follow up with client.",
            "owner_id": str(owner_membership.user_id),
            "due_date": "2026-12-01",
        },
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["owner_id"] == str(owner_membership.user_id)
    assert body["due_date"] == "2026-12-01"


async def test_create_action_rejects_owner_not_in_organization(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.MEMBER)
    meeting = await make_meeting(
        db_session, organization=actor.organization, created_by=actor.membership
    )
    other_org = await make_organization(db_session)
    outsider_user = await make_user(db_session, email=f"action-outsider-{other_org.id}@x.com")
    await db_session.commit()

    response = await client.post(
        f"/api/v1/meetings/{meeting.id}/actions",
        json={"description": "Should fail.", "owner_id": str(outsider_user.id)},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == 400


async def test_non_creator_member_cannot_add_an_action_item(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    creator_actor = await login_as(client, fake_verifier, db_session, role=Role.MEMBER)
    meeting = await make_meeting(
        db_session, organization=creator_actor.organization, created_by=creator_actor.membership
    )
    outsider_user = await make_user(
        db_session, email=f"action-add-outsider-{creator_actor.organization.id}@x.com"
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
        f"/api/v1/meetings/{meeting.id}/actions",
        json={"description": "Hijack"},
        headers={"X-CSRF-Token": outsider.csrf_token},
    )
    assert response.status_code == 403


async def test_create_action_records_feed_event_not_audit_event(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.MEMBER)
    meeting = await make_meeting(
        db_session, organization=actor.organization, created_by=actor.membership
    )
    await db_session.commit()

    response = await client.post(
        f"/api/v1/meetings/{meeting.id}/actions",
        json={"description": "Feed check."},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == 201
    action_id = response.json()["id"]

    feed_rows = await list_feed(db_session, organization_id=actor.organization.id)
    created_events = [e for e in feed_rows if str(e.entity_id) == action_id]
    assert len(created_events) == 1
    assert created_events[0].event == "meeting_action.created"


async def test_list_actions_visible_to_anyone_who_can_see_the_meeting(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.MEMBER)
    meeting = await make_meeting(
        db_session, organization=actor.organization, created_by=actor.membership
    )
    await db_session.commit()
    await client.post(
        f"/api/v1/meetings/{meeting.id}/actions",
        json={"description": "One."},
        headers={"X-CSRF-Token": actor.csrf_token},
    )

    response = await client.get(f"/api/v1/meetings/{meeting.id}/actions")
    assert response.status_code == 200
    assert response.json()["total"] == 1


async def test_creator_can_update_an_action_item(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.MEMBER)
    meeting = await make_meeting(
        db_session, organization=actor.organization, created_by=actor.membership
    )
    await db_session.commit()
    create_response = await client.post(
        f"/api/v1/meetings/{meeting.id}/actions",
        json={"description": "Original."},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    action_id = create_response.json()["id"]

    response = await client.patch(
        f"/api/v1/meetings/{meeting.id}/actions/{action_id}",
        json={"description": "Updated."},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == 200
    assert response.json()["description"] == "Updated."


async def test_update_action_cannot_set_task_id(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    """MeetingActionUpdateRequest doesn't accept task_id at all — an
    unknown field is silently ignored by Pydantic (not an error), so this
    proves it has no effect, not just that the schema rejects it."""
    actor = await login_as(client, fake_verifier, db_session, role=Role.MEMBER)
    meeting = await make_meeting(
        db_session, organization=actor.organization, created_by=actor.membership
    )
    await db_session.commit()
    create_response = await client.post(
        f"/api/v1/meetings/{meeting.id}/actions",
        json={"description": "Original."},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    action_id = create_response.json()["id"]

    response = await client.patch(
        f"/api/v1/meetings/{meeting.id}/actions/{action_id}",
        json={"task_id": "01923f6e-6e2e-7f3e-8f3e-6e2e7f3e8f3e"},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == 200
    assert response.json()["task_id"] is None


async def test_non_creator_member_cannot_update_an_action_item(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    creator_actor = await login_as(client, fake_verifier, db_session, role=Role.MEMBER)
    meeting = await make_meeting(
        db_session, organization=creator_actor.organization, created_by=creator_actor.membership
    )
    await db_session.commit()
    create_response = await client.post(
        f"/api/v1/meetings/{meeting.id}/actions",
        json={"description": "Original."},
        headers={"X-CSRF-Token": creator_actor.csrf_token},
    )
    action_id = create_response.json()["id"]

    outsider_user = await make_user(
        db_session, email=f"action-patch-outsider-{creator_actor.organization.id}@x.com"
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
        f"/api/v1/meetings/{meeting.id}/actions/{action_id}",
        json={"description": "Hijack"},
        headers={"X-CSRF-Token": outsider.csrf_token},
    )
    assert response.status_code == 403


async def test_creator_can_delete_an_action_item(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.MEMBER)
    meeting = await make_meeting(
        db_session, organization=actor.organization, created_by=actor.membership
    )
    await db_session.commit()
    create_response = await client.post(
        f"/api/v1/meetings/{meeting.id}/actions",
        json={"description": "Delete me."},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    action_id = create_response.json()["id"]

    response = await client.delete(
        f"/api/v1/meetings/{meeting.id}/actions/{action_id}",
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == 204


async def test_delete_action_records_audit_event_per_adr_0011(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.MEMBER)
    meeting = await make_meeting(
        db_session, organization=actor.organization, created_by=actor.membership
    )
    await db_session.commit()
    create_response = await client.post(
        f"/api/v1/meetings/{meeting.id}/actions",
        json={"description": "Delete me."},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    action_id = create_response.json()["id"]

    await client.delete(
        f"/api/v1/meetings/{meeting.id}/actions/{action_id}",
        headers={"X-CSRF-Token": actor.csrf_token},
    )

    audit_rows = await list_audit(db_session, organization_id=actor.organization.id)
    deleted_events = [e for e in audit_rows if str(e.entity_id) == action_id]
    assert len(deleted_events) == 1
    assert deleted_events[0].event == "meeting_action.deleted"


async def test_non_creator_member_cannot_delete_an_action_item(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    creator_actor = await login_as(client, fake_verifier, db_session, role=Role.MEMBER)
    meeting = await make_meeting(
        db_session, organization=creator_actor.organization, created_by=creator_actor.membership
    )
    await db_session.commit()
    create_response = await client.post(
        f"/api/v1/meetings/{meeting.id}/actions",
        json={"description": "Keep me."},
        headers={"X-CSRF-Token": creator_actor.csrf_token},
    )
    action_id = create_response.json()["id"]

    outsider_user = await make_user(
        db_session, email=f"action-delete-outsider-{creator_actor.organization.id}@x.com"
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
        f"/api/v1/meetings/{meeting.id}/actions/{action_id}",
        headers={"X-CSRF-Token": outsider.csrf_token},
    )
    assert response.status_code == 403


async def test_get_action_in_another_org_meeting_is_404(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    other_org = await make_organization(db_session)
    other_owner_user = await make_user(db_session, email=f"action-other-{other_org.id}@x.com")
    other_owner_membership = await make_membership(
        db_session, organization=other_org, user=other_owner_user, role=Role.OWNER
    )
    other_meeting = await make_meeting(
        db_session, organization=other_org, created_by=other_owner_membership
    )
    await db_session.commit()

    await login_as(client, fake_verifier, db_session, role=Role.ADMIN)
    response = await client.get(f"/api/v1/meetings/{other_meeting.id}/actions")
    assert response.status_code == 404

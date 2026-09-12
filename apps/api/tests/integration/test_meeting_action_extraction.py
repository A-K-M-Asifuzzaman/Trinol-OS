from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.factories import (
    make_meeting,
    make_membership,
    make_organization,
    make_user,
)
from tests.helpers import login_as, login_as_existing
from trinol.core.authz.permissions import Role
from trinol.platform.activity import list_feed

# Reuses the meeting's own edit rule (meeting_service.can_write_meeting) —
# no separate permission, same as meeting summaries (Phase 8 Stage 1).

pytestmark = pytest.mark.usefixtures("db_session")


async def test_creator_can_extract_actions(
    client: AsyncClient, fake_verifier, fake_ai_client, db_session
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.MEMBER)
    meeting = await make_meeting(
        db_session, organization=actor.organization, created_by=actor.membership
    )
    await db_session.commit()
    fake_ai_client.next_response = "Draft the timeline\nFollow up with finance"

    response = await client.post(
        f"/api/v1/meetings/{meeting.id}/actions/extract",
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["total"] == 2
    descriptions = {item["description"] for item in body["items"]}
    assert descriptions == {"Draft the timeline", "Follow up with finance"}
    for item in body["items"]:
        assert item["source"] == "AI"
        assert item["task_id"] is None


async def test_extraction_is_capped_at_ten_even_with_more_suggestions(
    client: AsyncClient, fake_verifier, fake_ai_client, db_session
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.MEMBER)
    meeting = await make_meeting(
        db_session, organization=actor.organization, created_by=actor.membership
    )
    await db_session.commit()
    fake_ai_client.next_response = "\n".join(f"Action item {i}" for i in range(30))

    response = await client.post(
        f"/api/v1/meetings/{meeting.id}/actions/extract",
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["total"] == 10
    assert len(body["items"]) == 10


async def test_extraction_parses_numbered_and_bulleted_lines(
    client: AsyncClient, fake_verifier, fake_ai_client, db_session
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.MEMBER)
    meeting = await make_meeting(
        db_session, organization=actor.organization, created_by=actor.membership
    )
    await db_session.commit()
    fake_ai_client.next_response = "1. Draft the timeline\n- Follow up with finance\n\n"

    response = await client.post(
        f"/api/v1/meetings/{meeting.id}/actions/extract",
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == 201
    descriptions = {item["description"] for item in response.json()["items"]}
    assert descriptions == {"Draft the timeline", "Follow up with finance"}


async def test_no_suggestions_creates_no_rows_and_no_feed_event(
    client: AsyncClient, fake_verifier, fake_ai_client, db_session
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.MEMBER)
    meeting = await make_meeting(
        db_session, organization=actor.organization, created_by=actor.membership
    )
    await db_session.commit()
    fake_ai_client.next_response = "\n\n"

    response = await client.post(
        f"/api/v1/meetings/{meeting.id}/actions/extract",
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == 201
    assert response.json() == {"items": [], "total": 0}

    feed_rows = await list_feed(db_session, organization_id=actor.organization.id)
    assert not [e for e in feed_rows if e.event == "meeting_action.ai_extracted"]


async def test_non_creator_member_cannot_extract_actions(
    client: AsyncClient, fake_verifier, fake_ai_client, db_session
) -> None:
    creator_actor = await login_as(client, fake_verifier, db_session, role=Role.MEMBER)
    meeting = await make_meeting(
        db_session, organization=creator_actor.organization, created_by=creator_actor.membership
    )
    outsider_user = await make_user(
        db_session, email=f"extract-outsider-{creator_actor.organization.id}@x.com"
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
        f"/api/v1/meetings/{meeting.id}/actions/extract",
        headers={"X-CSRF-Token": outsider.csrf_token},
    )
    assert response.status_code == 403
    assert fake_ai_client.calls == []


async def test_extracted_action_can_be_deleted_through_existing_endpoint(
    client: AsyncClient, fake_verifier, fake_ai_client, db_session
) -> None:
    """No new review/approve flow — a bad suggestion is deleted through the
    same DELETE /actions/{action_id} endpoint any human-authored action
    already uses (Phase 8 Stage 2 plan decision)."""
    actor = await login_as(client, fake_verifier, db_session, role=Role.MEMBER)
    meeting = await make_meeting(
        db_session, organization=actor.organization, created_by=actor.membership
    )
    await db_session.commit()
    fake_ai_client.next_response = "A bad suggestion"

    extract_response = await client.post(
        f"/api/v1/meetings/{meeting.id}/actions/extract",
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    action_id = extract_response.json()["items"][0]["id"]

    delete_response = await client.delete(
        f"/api/v1/meetings/{meeting.id}/actions/{action_id}",
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert delete_response.status_code == 204


async def test_extract_actions_for_another_org_meeting_is_404(
    client: AsyncClient, fake_verifier, fake_ai_client, db_session
) -> None:
    other_org = await make_organization(db_session)
    other_owner_user = await make_user(db_session, email=f"extract-other-{other_org.id}@x.com")
    other_owner_membership = await make_membership(
        db_session, organization=other_org, user=other_owner_user, role=Role.OWNER
    )
    other_meeting = await make_meeting(
        db_session, organization=other_org, created_by=other_owner_membership
    )
    await db_session.commit()

    actor = await login_as(client, fake_verifier, db_session, role=Role.ADMIN)
    response = await client.post(
        f"/api/v1/meetings/{other_meeting.id}/actions/extract",
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == 404
    assert fake_ai_client.calls == []

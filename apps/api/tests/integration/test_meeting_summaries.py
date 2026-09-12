from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.factories import (
    make_meeting,
    make_meeting_participant,
    make_meeting_summary,
    make_membership,
    make_organization,
    make_user,
)
from tests.helpers import login_as, login_as_existing
from trinol.core.authz.permissions import Role
from trinol.platform.activity import list_feed

# Reuses the meeting's own edit/visibility rule (meeting_service.
# can_write_meeting/ensure_meeting_visible) — no separate permission, no
# ownership-split of its own (Phase 8 Stage 1 plan).

pytestmark = pytest.mark.usefixtures("db_session")


async def test_creator_can_summarize_a_meeting(
    client: AsyncClient, fake_verifier, fake_ai_client, db_session
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.MEMBER)
    meeting = await make_meeting(
        db_session, organization=actor.organization, created_by=actor.membership
    )
    await db_session.commit()

    response = await client.post(
        f"/api/v1/meetings/{meeting.id}/summary",
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["meeting_id"] == str(meeting.id)
    assert body["content"].startswith("[fake summary of")
    assert body["generated_by"] == str(actor.membership.user_id)
    # Never a real network call — the fake client is the only AIClient this
    # test (or any test) ever talks to.
    assert len(fake_ai_client.calls) == 1


async def test_non_creator_member_cannot_summarize(
    client: AsyncClient, fake_verifier, fake_ai_client, db_session
) -> None:
    creator_actor = await login_as(client, fake_verifier, db_session, role=Role.MEMBER)
    meeting = await make_meeting(
        db_session, organization=creator_actor.organization, created_by=creator_actor.membership
    )
    outsider_user = await make_user(
        db_session, email=f"summary-outsider-{creator_actor.organization.id}@x.com"
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
        f"/api/v1/meetings/{meeting.id}/summary",
        headers={"X-CSRF-Token": outsider.csrf_token},
    )
    assert response.status_code == 403
    assert fake_ai_client.calls == []


@pytest.mark.parametrize("role", [Role.MANAGER, Role.ADMIN, Role.OWNER])
async def test_manager_and_up_can_summarize_a_meeting_they_did_not_create(
    client: AsyncClient, fake_verifier, fake_ai_client, db_session, role: Role
) -> None:
    creator_actor = await login_as(client, fake_verifier, db_session, role=Role.MEMBER)
    meeting = await make_meeting(
        db_session, organization=creator_actor.organization, created_by=creator_actor.membership
    )
    manager_user = await make_user(
        db_session, email=f"summary-manager-{creator_actor.organization.id}@x.com"
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
        f"/api/v1/meetings/{meeting.id}/summary",
        headers={"X-CSRF-Token": manager.csrf_token},
    )
    assert response.status_code == 200


async def test_get_summary_before_generation_is_404(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.MEMBER)
    meeting = await make_meeting(
        db_session, organization=actor.organization, created_by=actor.membership
    )
    await db_session.commit()

    response = await client.get(f"/api/v1/meetings/{meeting.id}/summary")
    assert response.status_code == 404


async def test_participant_can_view_but_not_generate_a_summary(
    client: AsyncClient, fake_verifier, fake_ai_client, db_session
) -> None:
    creator_actor = await login_as(client, fake_verifier, db_session, role=Role.MEMBER)
    meeting = await make_meeting(
        db_session, organization=creator_actor.organization, created_by=creator_actor.membership
    )
    participant_user = await make_user(
        db_session, email=f"summary-participant-{creator_actor.organization.id}@x.com"
    )
    participant_membership = await make_membership(
        db_session, organization=creator_actor.organization, user=participant_user, role=Role.MEMBER
    )
    await make_meeting_participant(db_session, meeting=meeting, user=participant_membership)
    await db_session.commit()

    await client.post(
        f"/api/v1/meetings/{meeting.id}/summary",
        headers={"X-CSRF-Token": creator_actor.csrf_token},
    )

    participant = await login_as_existing(
        client,
        fake_verifier,
        user=participant_user,
        membership=participant_membership,
        organization=creator_actor.organization,
    )
    get_response = await client.get(f"/api/v1/meetings/{meeting.id}/summary")
    assert get_response.status_code == 200

    post_response = await client.post(
        f"/api/v1/meetings/{meeting.id}/summary",
        headers={"X-CSRF-Token": participant.csrf_token},
    )
    assert post_response.status_code == 403


async def test_summarize_records_feed_event(
    client: AsyncClient, fake_verifier, fake_ai_client, db_session
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.MEMBER)
    meeting = await make_meeting(
        db_session, organization=actor.organization, created_by=actor.membership
    )
    await db_session.commit()

    response = await client.post(
        f"/api/v1/meetings/{meeting.id}/summary",
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == 200

    feed_rows = await list_feed(db_session, organization_id=actor.organization.id)
    created_events = [e for e in feed_rows if str(e.entity_id) == str(meeting.id)]
    assert len(created_events) == 1
    assert created_events[0].event == "meeting_summary.generated"


async def test_regenerating_a_summary_replaces_content_without_duplicating(
    client: AsyncClient, fake_verifier, fake_ai_client, db_session
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.MEMBER)
    meeting = await make_meeting(
        db_session, organization=actor.organization, created_by=actor.membership
    )
    await db_session.commit()

    first = await client.post(
        f"/api/v1/meetings/{meeting.id}/summary",
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    second = await client.post(
        f"/api/v1/meetings/{meeting.id}/summary",
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["id"] == second.json()["id"]

    get_response = await client.get(f"/api/v1/meetings/{meeting.id}/summary")
    assert get_response.status_code == 200
    assert get_response.json()["id"] == first.json()["id"]
    assert len(fake_ai_client.calls) == 2


async def test_summary_routes_for_another_org_meeting_are_404(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    other_org = await make_organization(db_session)
    other_owner_user = await make_user(db_session, email=f"summary-other-{other_org.id}@x.com")
    other_owner_membership = await make_membership(
        db_session, organization=other_org, user=other_owner_user, role=Role.OWNER
    )
    other_meeting = await make_meeting(
        db_session, organization=other_org, created_by=other_owner_membership
    )
    # Pre-seed a real summary so a 404 here proves cross-org isolation,
    # not merely "not summarized yet" (which would 404 either way).
    await make_meeting_summary(
        db_session, meeting=other_meeting, generated_by=other_owner_membership
    )
    await db_session.commit()

    actor = await login_as(client, fake_verifier, db_session, role=Role.ADMIN)
    get_response = await client.get(f"/api/v1/meetings/{other_meeting.id}/summary")
    assert get_response.status_code == 404
    post_response = await client.post(
        f"/api/v1/meetings/{other_meeting.id}/summary",
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert post_response.status_code == 404

from __future__ import annotations

import asyncio

import pytest
from dotenv import dotenv_values
from httpx import AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import create_async_engine

from tests.factories import (
    make_meeting,
    make_meeting_participant,
    make_membership,
    make_organization,
    make_user,
)
from tests.helpers import login_as, login_as_existing
from trinol.core.authz.permissions import Role
from trinol.core.config import _ENV_FILE
from trinol.core.db.engine import get_session_factory
from trinol.core.errors import ConflictError
from trinol.modules.identity.models import Membership, Organization, User
from trinol.modules.meetings.models import Meeting, MeetingParticipant
from trinol.modules.meetings.services.meeting_participant_service import add_participant
from trinol.platform.activity import list_audit, list_feed
from trinol.platform.models import ActivityEvent

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


async def _cleanup_race_test_rows(session_factory, *, organization_id, user_ids: list) -> None:
    """Codex P1 (Stage 3 re-review): the concurrent-add tests below use
    real commits outside any test fixture's rollback boundary — leaving
    them behind pollutes the shared database for every later test run,
    the same trap test_lead_conversion.py's own race test already solved.
    Full FK-ordered cleanup, mirroring that test's exact pattern:
    MeetingParticipant (child of Meeting) before Meeting, before
    Membership, before User, before Organization — matches the
    composite-FK RESTRICT chain in DATABASE.md §5.1/§5.2. ActivityEvent
    needs the migrator role separately (trinol_app is REVOKEd from
    UPDATE/DELETE on it, ADR-0006); everything else is a plain app-role
    delete."""
    migration_url = dotenv_values(_ENV_FILE)["DATABASE_MIGRATION_URL"]
    assert migration_url is not None
    migrator_engine = create_async_engine(migration_url)
    try:
        async with migrator_engine.begin() as conn:
            await conn.execute(
                ActivityEvent.__table__.delete().where(
                    ActivityEvent.organization_id == organization_id
                )
            )
    finally:
        await migrator_engine.dispose()

    cleanup_session = session_factory()
    try:
        await cleanup_session.execute(
            delete(MeetingParticipant).where(MeetingParticipant.organization_id == organization_id)
        )
        await cleanup_session.execute(
            delete(Meeting).where(Meeting.organization_id == organization_id)
        )
        await cleanup_session.execute(
            delete(Membership).where(Membership.organization_id == organization_id)
        )
        for user_id in user_ids:
            await cleanup_session.execute(delete(User).where(User.id == user_id))
        await cleanup_session.execute(
            delete(Organization).where(Organization.id == organization_id)
        )
        await cleanup_session.commit()
    finally:
        await cleanup_session.close()


async def test_concurrent_add_by_user_id_only_one_succeeds() -> None:
    """Codex P1: add_participant's duplicate check was a bare
    check-then-insert with no lock and no matching DB uniqueness
    constraint, so two concurrent adds for the same user_id could both
    pass it. Needs two genuinely independent DB connections, not two
    SAVEPOINTs sharing one transaction — the point is Postgres actually
    serializing the two via the meeting row's own FOR UPDATE lock
    (meeting_service.get_meeting_in_org's for_update=True), same approach
    as test_lead_conversion.py's convert_lead race test. Real commits, no
    test fixtures — cleaned up explicitly at the end."""
    session_factory = get_session_factory()

    setup_session = session_factory()
    try:
        org = await make_organization(setup_session)
        creator_user = await make_user(setup_session, email=f"race-creator-{org.id}@x.com")
        creator = await make_membership(
            setup_session, organization=org, user=creator_user, role=Role.MEMBER
        )
        meeting = await make_meeting(setup_session, organization=org, created_by=creator)
        invitee_user = await make_user(setup_session, email=f"race-invitee-{org.id}@x.com")
        await make_membership(setup_session, organization=org, user=invitee_user, role=Role.MEMBER)
        await setup_session.commit()
        org_id, creator_id, meeting_id, creator_user_id, invitee_user_id = (
            org.id,
            creator.id,
            meeting.id,
            creator_user.id,
            invitee_user.id,
        )
    finally:
        await setup_session.close()

    session_1 = session_factory()
    session_2 = session_factory()
    try:
        actor_1 = (
            await session_1.execute(
                select(Membership).where(
                    Membership.organization_id == org_id, Membership.id == creator_id
                )
            )
        ).scalar_one()
        actor_2 = (
            await session_2.execute(
                select(Membership).where(
                    Membership.organization_id == org_id, Membership.id == creator_id
                )
            )
        ).scalar_one()

        results = await asyncio.gather(
            add_participant(
                session_1,
                organization_id=org_id,
                actor=actor_1,
                meeting_id=meeting_id,
                user_id=invitee_user_id,
                external_email=None,
            ),
            add_participant(
                session_2,
                organization_id=org_id,
                actor=actor_2,
                meeting_id=meeting_id,
                user_id=invitee_user_id,
                external_email=None,
            ),
            return_exceptions=True,
        )

        successes = [r for r in results if not isinstance(r, Exception)]
        failures = [r for r in results if isinstance(r, Exception)]
        assert len(successes) == 1, f"expected exactly one success, got: {results}"
        assert len(failures) == 1
        assert isinstance(failures[0], ConflictError)

        remaining = (
            (
                await session_1.execute(
                    select(MeetingParticipant).where(
                        MeetingParticipant.organization_id == org_id,
                        MeetingParticipant.meeting_id == meeting_id,
                        MeetingParticipant.user_id == invitee_user_id,
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(remaining) == 1, "the race must never produce two participant rows"
    finally:
        await session_1.close()
        await session_2.close()
        await _cleanup_race_test_rows(
            session_factory,
            organization_id=org_id,
            user_ids=[creator_user_id, invitee_user_id],
        )


async def test_concurrent_add_by_external_email_only_one_succeeds() -> None:
    """Same race, other identity path (external_email instead of
    user_id) — the fix is the same meeting-row lock either way, but the
    duplicate check queries a different column, so it's worth proving
    both paths are actually covered, not just one."""
    session_factory = get_session_factory()

    setup_session = session_factory()
    try:
        org = await make_organization(setup_session)
        creator_user = await make_user(setup_session, email=f"race-email-creator-{org.id}@x.com")
        creator = await make_membership(
            setup_session, organization=org, user=creator_user, role=Role.MEMBER
        )
        meeting = await make_meeting(setup_session, organization=org, created_by=creator)
        await setup_session.commit()
        org_id, creator_id, meeting_id, creator_user_id = (
            org.id,
            creator.id,
            meeting.id,
            creator_user.id,
        )
    finally:
        await setup_session.close()

    session_1 = session_factory()
    session_2 = session_factory()
    try:
        actor_1 = (
            await session_1.execute(
                select(Membership).where(
                    Membership.organization_id == org_id, Membership.id == creator_id
                )
            )
        ).scalar_one()
        actor_2 = (
            await session_2.execute(
                select(Membership).where(
                    Membership.organization_id == org_id, Membership.id == creator_id
                )
            )
        ).scalar_one()

        results = await asyncio.gather(
            add_participant(
                session_1,
                organization_id=org_id,
                actor=actor_1,
                meeting_id=meeting_id,
                user_id=None,
                external_email="race-guest@example.test",
            ),
            add_participant(
                session_2,
                organization_id=org_id,
                actor=actor_2,
                meeting_id=meeting_id,
                user_id=None,
                external_email="race-guest@example.test",
            ),
            return_exceptions=True,
        )

        successes = [r for r in results if not isinstance(r, Exception)]
        failures = [r for r in results if isinstance(r, Exception)]
        assert len(successes) == 1, f"expected exactly one success, got: {results}"
        assert len(failures) == 1
        assert isinstance(failures[0], ConflictError)

        remaining = (
            (
                await session_1.execute(
                    select(MeetingParticipant).where(
                        MeetingParticipant.organization_id == org_id,
                        MeetingParticipant.meeting_id == meeting_id,
                        MeetingParticipant.external_email == "race-guest@example.test",
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(remaining) == 1, "the race must never produce two participant rows"
    finally:
        await session_1.close()
        await session_2.close()
        await _cleanup_race_test_rows(
            session_factory, organization_id=org_id, user_ids=[creator_user_id]
        )

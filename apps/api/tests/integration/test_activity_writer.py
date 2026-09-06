from __future__ import annotations

from datetime import timedelta

from httpx import AsyncClient
from sqlalchemy import select

from tests.factories import make_invitation, make_membership, make_organization, make_user
from trinol.core.authz.permissions import Role
from trinol.core.ids import uuid7
from trinol.modules.identity.identity_verifier import VerifiedIdentity
from trinol.modules.identity.models import MembershipStatus
from trinol.modules.identity.services.membership_service import change_role, remove_member
from trinol.platform.activity import list_audit, list_feed, record
from trinol.platform.models import ActivityEvent

# ADR-0006: one append-only table serving both the activity feed
# (is_audit=false, none exist yet — Phase 1 has no work/CRM content) and the
# audit log (is_audit=true, exercised throughout this file).


async def test_record_writes_a_row_with_the_given_fields(db_session) -> None:
    org = await make_organization(db_session)
    user = await make_user(db_session)
    await db_session.commit()

    event = await record(
        db_session,
        organization_id=org.id,
        event="test.thing_happened",
        entity_type="user",
        entity_id=user.id,
        actor_id=user.id,
        metadata={"key": "value"},
        audit=True,
        ip="203.0.113.1",
    )
    await db_session.commit()

    refreshed = (
        await db_session.execute(
            select(ActivityEvent).where(
                ActivityEvent.organization_id == org.id, ActivityEvent.id == event.id
            )
        )
    ).scalar_one()
    assert refreshed.event == "test.thing_happened"
    assert refreshed.entity_type == "user"
    assert refreshed.entity_id == user.id
    assert refreshed.actor_id == user.id
    assert refreshed.event_metadata == {"key": "value"}
    assert refreshed.is_audit is True
    assert refreshed.ip == "203.0.113.1"


async def test_list_audit_returns_only_audit_rows(db_session) -> None:
    org = await make_organization(db_session)
    user = await make_user(db_session)
    await db_session.commit()

    await record(
        db_session,
        organization_id=org.id,
        event="test.audit_one",
        entity_type="user",
        entity_id=user.id,
        audit=True,
    )
    await record(
        db_session,
        organization_id=org.id,
        event="test.feed_one",
        entity_type="user",
        entity_id=user.id,
        audit=False,
    )
    await db_session.commit()

    audit_rows = await list_audit(db_session, organization_id=org.id)
    feed_rows = await list_feed(db_session, organization_id=org.id)

    assert [row.event for row in audit_rows] == ["test.audit_one"]
    assert [row.event for row in feed_rows] == ["test.feed_one"]


async def test_no_feed_events_exist_yet(db_session) -> None:
    """Phase 1 has no work/CRM content, so nothing should ever produce an
    is_audit=false row yet — every event this phase writes is audit-only."""
    org = await make_organization(db_session)
    await db_session.commit()
    assert await list_feed(db_session, organization_id=org.id) == []


def _identity(*, firebase_uid: str, email: str) -> VerifiedIdentity:
    return VerifiedIdentity(
        firebase_uid=firebase_uid,
        email=email,
        email_verified=True,
        sign_in_provider="password",
        full_name="Test Person",
        avatar_url=None,
    )


async def test_successful_login_writes_an_audit_event(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    org = await make_organization(db_session)
    user = await make_user(db_session, email="login@x.com")
    await make_membership(db_session, organization=org, user=user, role=Role.MEMBER)
    await db_session.commit()

    fake_verifier.register("tok", _identity(firebase_uid=user.firebase_uid, email=user.email))
    response = await client.post("/api/v1/auth/session", json={"id_token": "tok"})
    assert response.status_code == 200

    rows = await list_audit(db_session, organization_id=org.id)
    assert [row.event for row in rows] == ["auth.session.created"]
    assert rows[0].actor_id == user.id


async def test_inactive_membership_rejection_writes_an_audit_event(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    org = await make_organization(db_session)
    user = await make_user(db_session, email="inactive@x.com")
    await make_membership(db_session, organization=org, user=user, status=MembershipStatus.INACTIVE)
    await db_session.commit()

    fake_verifier.register("tok", _identity(firebase_uid=user.firebase_uid, email=user.email))
    response = await client.post("/api/v1/auth/session", json={"id_token": "tok"})
    assert response.status_code == 403

    rows = await list_audit(db_session, organization_id=org.id)
    assert [row.event for row in rows] == ["auth.exchange.rejected"]
    assert rows[0].event_metadata["reason"] == "membership_inactive"


async def test_expired_invitation_rejection_writes_an_audit_event(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    org = await make_organization(db_session)
    inviter = await make_user(db_session, email="inviter@x.com")
    invitation = await make_invitation(
        db_session,
        organization=org,
        email="expired@x.com",
        invited_by=inviter,
        expires_in=timedelta(days=-1),
    )
    await db_session.commit()

    fake_verifier.register("tok", _identity(firebase_uid=f"fb-{uuid7()}", email="expired@x.com"))
    response = await client.post("/api/v1/auth/session", json={"id_token": "tok"})
    assert response.status_code == 403

    rows = await list_audit(db_session, organization_id=org.id)
    assert [row.event for row in rows] == ["auth.exchange.rejected"]
    assert rows[0].entity_type == "invitation"
    assert rows[0].entity_id == invitation.id
    assert rows[0].event_metadata["reason"] == "invitation_expired"


async def test_unknown_identity_with_no_invitation_writes_no_event(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    """The one documented gap (AUTH.md §5): no organization is determinable
    here, and activity_events.organization_id is NOT NULL, so this rejection
    is logged (core/logging.py), not written to activity_events at all."""
    org = await make_organization(db_session)
    await db_session.commit()

    fake_verifier.register("tok", _identity(firebase_uid=f"fb-{uuid7()}", email="nobody@x.com"))
    response = await client.post("/api/v1/auth/session", json={"id_token": "tok"})
    assert response.status_code == 403

    assert await list_audit(db_session, organization_id=org.id) == []


async def test_role_change_writes_an_audit_event(db_session) -> None:
    org = await make_organization(db_session)
    owner_user = await make_user(db_session, email="owner@x.com")
    target_user = await make_user(db_session, email="target@x.com")
    owner = await make_membership(db_session, organization=org, user=owner_user, role=Role.OWNER)
    target = await make_membership(
        db_session, organization=org, user=target_user, role=Role.MANAGER
    )
    await db_session.commit()

    await change_role(
        db_session,
        organization_id=org.id,
        actor=owner,
        target_membership_id=target.id,
        new_role=Role.ADMIN,
    )

    rows = await list_audit(db_session, organization_id=org.id)
    assert [row.event for row in rows] == ["membership.role_changed"]
    assert rows[0].entity_id == target.id
    assert rows[0].actor_id == owner.user_id
    assert rows[0].event_metadata == {"from_role": "MANAGER", "to_role": "ADMIN"}


async def test_member_removal_writes_an_audit_event(db_session) -> None:
    org = await make_organization(db_session)
    owner_user = await make_user(db_session, email="owner2@x.com")
    target_user = await make_user(db_session, email="target2@x.com")
    owner = await make_membership(db_session, organization=org, user=owner_user, role=Role.OWNER)
    target = await make_membership(db_session, organization=org, user=target_user, role=Role.MEMBER)
    await db_session.commit()

    await remove_member(
        db_session, organization_id=org.id, actor=owner, target_membership_id=target.id
    )

    rows = await list_audit(db_session, organization_id=org.id)
    assert [row.event for row in rows] == ["membership.removed"]
    assert rows[0].entity_id == target.id
    assert rows[0].event_metadata == {"role": "MEMBER"}

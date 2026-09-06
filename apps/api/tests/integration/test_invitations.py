from __future__ import annotations

import asyncio
import hashlib
from datetime import UTC, datetime, timedelta

import pytest
from dotenv import dotenv_values
from httpx import AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import create_async_engine

from tests.factories import make_invitation, make_membership, make_organization, make_user
from trinol.core.authz.permissions import Role
from trinol.core.config import _ENV_FILE
from trinol.core.db.engine import get_session_factory
from trinol.core.errors import ConflictError, ForbiddenError, NotFoundError
from trinol.modules.identity.identity_verifier import VerifiedIdentity
from trinol.modules.identity.models import (
    Invitation,
    Membership,
    MembershipStatus,
    Organization,
    User,
)
from trinol.modules.identity.services.invitation_service import (
    create_invitation,
    get_invitation_preview,
    list_open_invitations,
)
from trinol.platform.models import ActivityEvent

# Stage 8 (Phase 1 plan, decision 3): invitation creation/preview, plus the
# sign-in path completing acceptance — that last part is already exercised in
# test_auth_exchange.py's test_unknown_uid_with_open_invitation_provisions_and_returns_200,
# not repeated here.


async def _setup(db_session):
    org = await make_organization(db_session)
    owner_user = await make_user(db_session, email="owner@x.com")
    admin_user = await make_user(db_session, email="admin@x.com")
    manager_user = await make_user(db_session, email="manager@x.com")
    owner = await make_membership(db_session, organization=org, user=owner_user, role=Role.OWNER)
    admin = await make_membership(db_session, organization=org, user=admin_user, role=Role.ADMIN)
    manager = await make_membership(
        db_session, organization=org, user=manager_user, role=Role.MANAGER
    )
    await db_session.commit()
    return org, owner, admin, manager, owner_user


async def test_admin_can_invite_a_member(db_session) -> None:
    org, owner, admin, manager, owner_user = await _setup(db_session)
    result = await create_invitation(
        db_session,
        organization_id=org.id,
        actor=admin,
        email="new@x.com",
        role=Role.MEMBER,
    )
    assert result.invitation.email == "new@x.com"
    assert result.invitation.role == Role.MEMBER
    assert result.email_message.to == "new@x.com"


async def test_owner_can_invite_an_admin(db_session) -> None:
    org, owner, admin, manager, owner_user = await _setup(db_session)
    result = await create_invitation(
        db_session, organization_id=org.id, actor=owner, email="new@x.com", role=Role.ADMIN
    )
    assert result.invitation.role == Role.ADMIN


async def test_admin_cannot_invite_an_admin(db_session) -> None:
    org, owner, admin, manager, owner_user = await _setup(db_session)
    with pytest.raises(ForbiddenError, match="Only an OWNER"):
        await create_invitation(
            db_session, organization_id=org.id, actor=admin, email="new@x.com", role=Role.ADMIN
        )


async def test_manager_cannot_invite(db_session) -> None:
    org, owner, admin, manager, owner_user = await _setup(db_session)
    with pytest.raises(ForbiddenError, match="Insufficient role"):
        await create_invitation(
            db_session, organization_id=org.id, actor=manager, email="new@x.com", role=Role.MEMBER
        )


async def test_actor_from_another_organization_cannot_invite(db_session) -> None:
    org, owner, admin, manager, owner_user = await _setup(db_session)
    other_org = await make_organization(db_session)
    other_owner = await make_membership(
        db_session,
        organization=other_org,
        user=await make_user(db_session, email="otherowner@x.com"),
        role=Role.OWNER,
    )
    await db_session.commit()
    with pytest.raises(ForbiddenError, match="does not belong to this organization"):
        await create_invitation(
            db_session,
            organization_id=org.id,
            actor=other_owner,
            email="new@x.com",
            role=Role.MEMBER,
        )


async def test_cannot_invite_an_existing_active_member(db_session) -> None:
    org, owner, admin, manager, owner_user = await _setup(db_session)
    existing = await make_user(db_session, email="already-here@x.com")
    await make_membership(db_session, organization=org, user=existing, role=Role.MEMBER)
    await db_session.commit()

    with pytest.raises(ConflictError, match="already has a membership"):
        await create_invitation(
            db_session,
            organization_id=org.id,
            actor=admin,
            email="already-here@x.com",
            role=Role.MEMBER,
        )


async def test_cannot_invite_an_inactive_former_member(db_session) -> None:
    """Codex Stage 8 P1: creation only rejected ACTIVE memberships, but
    signing back in as an existing user never re-checks invitations
    (session_service._resolve_or_provision_user's "existing user" branch
    returns immediately) — so an invitation for a former member could never
    be consumed and would just sit there as a dead row."""
    org, owner, admin, manager, owner_user = await _setup(db_session)
    former = await make_user(db_session, email="former-member@x.com")
    await make_membership(
        db_session,
        organization=org,
        user=former,
        role=Role.MEMBER,
        status=MembershipStatus.INACTIVE,
    )
    await db_session.commit()

    with pytest.raises(ConflictError, match="already has a membership"):
        await create_invitation(
            db_session,
            organization_id=org.id,
            actor=admin,
            email="former-member@x.com",
            role=Role.MEMBER,
        )


async def test_cannot_invite_the_same_email_twice_while_open(db_session) -> None:
    org, owner, admin, manager, owner_user = await _setup(db_session)
    await make_invitation(
        db_session, organization=org, email="pending@x.com", invited_by=owner_user, role=Role.MEMBER
    )
    await db_session.commit()

    with pytest.raises(ConflictError, match="already exists"):
        await create_invitation(
            db_session,
            organization_id=org.id,
            actor=admin,
            email="pending@x.com",
            role=Role.MEMBER,
        )


async def test_expired_open_invitation_does_not_block_a_re_invite(db_session) -> None:
    org, owner, admin, manager, owner_user = await _setup(db_session)
    await make_invitation(
        db_session,
        organization=org,
        email="lapsed@x.com",
        invited_by=owner_user,
        role=Role.MEMBER,
        expires_in=timedelta(days=-1),
    )
    await db_session.commit()

    result = await create_invitation(
        db_session, organization_id=org.id, actor=admin, email="lapsed@x.com", role=Role.MEMBER
    )
    assert result.invitation.email == "lapsed@x.com"


async def test_list_open_invitations_excludes_accepted_and_expired(db_session) -> None:
    org, owner, admin, manager, owner_user = await _setup(db_session)
    open_invitation = await make_invitation(
        db_session, organization=org, email="open@x.com", invited_by=owner_user
    )
    accepted_invitation = await make_invitation(
        db_session, organization=org, email="accepted@x.com", invited_by=owner_user
    )
    accepted_invitation.accepted_at = datetime.now(UTC)
    await make_invitation(
        db_session,
        organization=org,
        email="expired@x.com",
        invited_by=owner_user,
        expires_in=timedelta(days=-1),
    )
    await db_session.commit()

    result = await list_open_invitations(db_session, organization_id=org.id, actor=admin)
    assert [inv.id for inv in result.items] == [open_invitation.id]
    assert result.total == 1


async def test_list_open_invitations_is_paginated(db_session) -> None:
    org, owner, admin, manager, owner_user = await _setup(db_session)
    for i in range(3):
        await make_invitation(
            db_session, organization=org, email=f"page-{i}@x.com", invited_by=owner_user
        )
    await db_session.commit()

    page = await list_open_invitations(
        db_session, organization_id=org.id, actor=admin, limit=2, offset=0
    )
    assert len(page.items) == 2
    assert page.total == 3

    second_page = await list_open_invitations(
        db_session, organization_id=org.id, actor=admin, limit=2, offset=2
    )
    assert len(second_page.items) == 1
    assert second_page.total == 3


async def test_manager_cannot_list_invitations(db_session) -> None:
    org, owner, admin, manager, owner_user = await _setup(db_session)
    with pytest.raises(ForbiddenError):
        await list_open_invitations(db_session, organization_id=org.id, actor=manager)


async def test_preview_returns_org_role_and_email_for_a_valid_token(db_session) -> None:
    org, owner, admin, manager, owner_user = await _setup(db_session)
    result = await create_invitation(
        db_session, organization_id=org.id, actor=admin, email="preview@x.com", role=Role.MANAGER
    )
    # The service returns the invitation row, not the raw token, so recover
    # the token the way an emailed invitee would: from the accept_url
    # embedded in the rendered email.
    accept_url = result.email_message.text_body.split("Accept your invitation: ")[1].split("\n")[0]
    raw_token = accept_url.split("token=")[1]

    preview = await get_invitation_preview(db_session, raw_token=raw_token)
    assert preview.organization_name == org.name
    assert preview.role == Role.MANAGER
    assert preview.email == "preview@x.com"


async def test_preview_404s_for_an_unknown_token(db_session) -> None:
    with pytest.raises(NotFoundError):
        await get_invitation_preview(db_session, raw_token="not-a-real-token")


async def test_preview_404s_for_an_expired_token(db_session) -> None:
    org, owner, admin, manager, owner_user = await _setup(db_session)
    raw_token = "expired-raw-token"
    await make_invitation(
        db_session,
        organization=org,
        email="expired@x.com",
        invited_by=owner_user,
        expires_in=timedelta(days=-1),
        token_hash=hashlib.sha256(raw_token.encode()).hexdigest(),
    )
    await db_session.commit()
    with pytest.raises(NotFoundError):
        await get_invitation_preview(db_session, raw_token=raw_token)


async def _login_as(client: AsyncClient, fake_verifier, db_session, *, role: Role) -> str:
    """Logs in as a freshly created member of that role in their own org and
    returns their CSRF token."""
    org = await make_organization(db_session)
    user = await make_user(db_session, email=f"{role.value.lower()}-{org.id}@x.com")
    await make_membership(db_session, organization=org, user=user, role=role)
    await db_session.commit()

    identity = VerifiedIdentity(
        firebase_uid=user.firebase_uid,
        email=user.email,
        email_verified=True,
        sign_in_provider="password",
        full_name=user.full_name,
        avatar_url=None,
    )
    fake_verifier.register(f"tok-{role.value}", identity)
    response = await client.post("/api/v1/auth/session", json={"id_token": f"tok-{role.value}"})
    assert response.status_code == 200
    return (await client.get("/api/v1/auth/session")).json()["csrf_token"]


async def test_admin_can_create_an_invitation_over_http(
    client: AsyncClient, fake_verifier, db_session, fake_email_sender
) -> None:
    csrf_token = await _login_as(client, fake_verifier, db_session, role=Role.ADMIN)

    response = await client.post(
        "/api/v1/invitations",
        json={"email": "invited-http@x.com", "role": "MEMBER"},
        headers={"X-CSRF-Token": csrf_token},
    )

    assert response.status_code == 201
    assert response.json()["email"] == "invited-http@x.com"
    assert len(fake_email_sender.sent) == 1
    assert fake_email_sender.sent[0].to == "invited-http@x.com"


async def test_manager_gets_403_creating_an_invitation_over_http(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    csrf_token = await _login_as(client, fake_verifier, db_session, role=Role.MANAGER)

    response = await client.post(
        "/api/v1/invitations",
        json={"email": "nope@x.com", "role": "MEMBER"},
        headers={"X-CSRF-Token": csrf_token},
    )

    assert response.status_code == 403


async def test_preview_endpoint_is_public_and_needs_no_auth(
    client: AsyncClient, fake_verifier, db_session, fake_email_sender
) -> None:
    csrf_token = await _login_as(client, fake_verifier, db_session, role=Role.OWNER)
    create_response = await client.post(
        "/api/v1/invitations",
        json={"email": "public-preview@x.com", "role": "MEMBER"},
        headers={"X-CSRF-Token": csrf_token},
    )
    assert create_response.status_code == 201
    accept_url = (
        fake_email_sender.sent[0].text_body.split("Accept your invitation: ")[1].split("\n")[0]
    )
    raw_token = accept_url.split("token=")[1]

    # A fresh, unauthenticated client — no cookie, no CSRF token — since this
    # is the page a not-yet-signed-in invitee lands on.
    response = await client.get(f"/api/v1/invitations/{raw_token}")

    assert response.status_code == 200
    body = response.json()
    assert body["email"] == "public-preview@x.com"
    assert body["role"] == "MEMBER"


async def test_preview_endpoint_404s_for_an_unknown_token(client: AsyncClient) -> None:
    response = await client.get("/api/v1/invitations/not-a-real-token")
    assert response.status_code == 404


async def test_concurrent_invitations_for_the_same_email_only_one_succeeds() -> None:
    """Codex Stage 8 P1: create_invitation's check-then-insert had no lock,
    so two simultaneous requests for the same org+email could both pass the
    "no open invitation exists" check and both insert. Needs two genuinely
    independent DB connections, not two SAVEPOINTs sharing one transaction —
    the point is Postgres actually serializing two concurrent transactions
    via the organization row's FOR UPDATE lock (organization_lock.py), same
    approach and same reason as test_escalation.py's last-owner-demotion
    test. Real commits, cleaned up explicitly at the end."""
    session_factory = get_session_factory()

    setup_session = session_factory()
    try:
        org = await make_organization(setup_session)
        admin_user = await make_user(setup_session, email=f"admin-{org.id}@x.com")
        admin = await make_membership(
            setup_session, organization=org, user=admin_user, role=Role.ADMIN
        )
        await setup_session.commit()
        org_id, admin_id, admin_user_id = org.id, admin.id, admin_user.id
    finally:
        await setup_session.close()

    session_1 = session_factory()
    session_2 = session_factory()
    try:
        actor_1 = (
            await session_1.execute(
                select(Membership).where(
                    Membership.organization_id == org_id, Membership.id == admin_id
                )
            )
        ).scalar_one()
        actor_2 = (
            await session_2.execute(
                select(Membership).where(
                    Membership.organization_id == org_id, Membership.id == admin_id
                )
            )
        ).scalar_one()

        results = await asyncio.gather(
            create_invitation(
                session_1,
                organization_id=org_id,
                actor=actor_1,
                email="race@x.com",
                role=Role.MEMBER,
            ),
            create_invitation(
                session_2,
                organization_id=org_id,
                actor=actor_2,
                email="race@x.com",
                role=Role.MEMBER,
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
                    select(Invitation).where(
                        Invitation.organization_id == org_id, Invitation.email == "race@x.com"
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(remaining) == 1, "the race must never produce two open invitations"
    finally:
        await session_1.close()
        await session_2.close()

        # See test_escalation.py's matching cleanup: trinol_app is REVOKEd
        # from UPDATE/DELETE on activity_events (ADR-0006), so the winning
        # create_invitation call's audit row needs the migrator role to clean up.
        migration_url = dotenv_values(_ENV_FILE)["DATABASE_MIGRATION_URL"]
        assert migration_url is not None
        migrator_engine = create_async_engine(migration_url)
        try:
            async with migrator_engine.begin() as conn:
                await conn.execute(
                    ActivityEvent.__table__.delete().where(ActivityEvent.organization_id == org_id)
                )
        finally:
            await migrator_engine.dispose()

        cleanup_session = session_factory()
        try:
            await cleanup_session.execute(
                delete(Invitation).where(Invitation.organization_id == org_id)
            )
            await cleanup_session.execute(
                delete(Membership).where(Membership.organization_id == org_id)
            )
            await cleanup_session.execute(delete(User).where(User.id == admin_user_id))
            await cleanup_session.execute(delete(Organization).where(Organization.id == org_id))
            await cleanup_session.commit()
        finally:
            await cleanup_session.close()

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient

from tests.factories import make_invitation, make_membership, make_organization, make_user
from trinol.core.authz.permissions import Role
from trinol.core.errors import ConflictError, ForbiddenError, NotFoundError
from trinol.modules.identity.identity_verifier import VerifiedIdentity
from trinol.modules.identity.services.invitation_service import (
    create_invitation,
    get_invitation_preview,
    list_open_invitations,
)

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

    with pytest.raises(ConflictError, match="already a member"):
        await create_invitation(
            db_session,
            organization_id=org.id,
            actor=admin,
            email="already-here@x.com",
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


async def test_list_open_invitations_excludes_accepted(db_session) -> None:
    org, owner, admin, manager, owner_user = await _setup(db_session)
    open_invitation = await make_invitation(
        db_session, organization=org, email="open@x.com", invited_by=owner_user
    )
    accepted_invitation = await make_invitation(
        db_session, organization=org, email="accepted@x.com", invited_by=owner_user
    )
    accepted_invitation.accepted_at = datetime.now(UTC)
    await db_session.commit()

    invitations = await list_open_invitations(db_session, organization_id=org.id, actor=admin)
    assert [inv.id for inv in invitations] == [open_invitation.id]


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

from __future__ import annotations

from httpx import AsyncClient
from sqlalchemy import select

from tests.factories import make_invitation, make_membership, make_organization, make_user
from trinol.core.authz.permissions import Role
from trinol.core.ids import uuid7
from trinol.modules.identity.identity_verifier import VerifiedIdentity
from trinol.modules.identity.models import Invitation, MembershipStatus, User


def _identity(
    *,
    firebase_uid: str | None = None,
    email: str = "person@example.com",
    email_verified: bool = True,
    sign_in_provider: str = "password",
    full_name: str | None = "Test Person",
    avatar_url: str | None = None,
) -> VerifiedIdentity:
    return VerifiedIdentity(
        firebase_uid=firebase_uid or f"fb-{uuid7()}",
        email=email,
        email_verified=email_verified,
        sign_in_provider=sign_in_provider,
        full_name=full_name,
        avatar_url=avatar_url,
    )


async def test_unknown_uid_no_invitation_returns_403(client: AsyncClient, fake_verifier) -> None:
    identity = _identity(email="stranger@example.com")
    fake_verifier.register("tok", identity)

    response = await client.post("/api/v1/auth/session", json={"id_token": "tok"})

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


async def test_unknown_uid_with_open_invitation_provisions_and_returns_200(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    org = await make_organization(db_session)
    inviter = await make_user(db_session, email="owner@example.com")
    invitation = await make_invitation(
        db_session,
        organization=org,
        email="invitee@example.com",
        invited_by=inviter,
        role=Role.MANAGER,
    )
    await db_session.commit()

    identity = _identity(email="invitee@example.com", full_name="Invitee Person")
    fake_verifier.register("tok", identity)

    response = await client.post("/api/v1/auth/session", json={"id_token": "tok"})

    assert response.status_code == 200
    body = response.json()
    assert body["organization_id"] == str(org.id)
    assert body["role"] == "MANAGER"
    assert "trinol_session" in response.cookies

    provisioned = (
        await db_session.execute(select(User).where(User.firebase_uid == identity.firebase_uid))
    ).scalar_one()
    assert provisioned.email == "invitee@example.com"
    assert provisioned.full_name == "Invitee Person"

    refreshed_invitation = (
        await db_session.execute(
            select(Invitation).where(
                Invitation.organization_id == org.id, Invitation.id == invitation.id
            )
        )
    ).scalar_one()
    assert refreshed_invitation.accepted_at is not None


async def test_inactive_membership_returns_403(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    org = await make_organization(db_session)
    user = await make_user(db_session, email="inactive@example.com")
    await make_membership(db_session, organization=org, user=user, status=MembershipStatus.INACTIVE)
    await db_session.commit()

    identity = _identity(firebase_uid=user.firebase_uid, email=user.email)
    fake_verifier.register("tok", identity)

    response = await client.post("/api/v1/auth/session", json={"id_token": "tok"})

    assert response.status_code == 403


async def test_unverified_email_returns_403(client: AsyncClient, fake_verifier) -> None:
    identity = _identity(email_verified=False)
    fake_verifier.register("tok", identity)

    response = await client.post("/api/v1/auth/session", json={"id_token": "tok"})

    assert response.status_code == 403


async def test_invalid_token_returns_401(client: AsyncClient, fake_verifier) -> None:
    response = await client.post(
        "/api/v1/auth/session", json={"id_token": "not-a-registered-token"}
    )

    assert response.status_code == 401


async def test_existing_user_successful_login_returns_200(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    org = await make_organization(db_session)
    user = await make_user(db_session, email="member@example.com")
    await make_membership(db_session, organization=org, user=user, role=Role.MEMBER)
    await db_session.commit()

    identity = _identity(firebase_uid=user.firebase_uid, email=user.email)
    fake_verifier.register("tok", identity)

    response = await client.post("/api/v1/auth/session", json={"id_token": "tok"})

    assert response.status_code == 200
    body = response.json()
    assert body["user_id"] == str(user.id)
    assert body["role"] == "MEMBER"


async def test_over_rate_limit_returns_429(client: AsyncClient, fake_verifier) -> None:
    # Rate limiting happens before token verification, so an invalid token is
    # enough to exercise it without registering 31 identities.
    last_response = None
    for _ in range(31):
        last_response = await client.post(
            "/api/v1/auth/session", json={"id_token": "never-registered"}
        )
    assert last_response is not None
    assert last_response.status_code == 429

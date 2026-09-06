from __future__ import annotations

from dataclasses import dataclass

from httpx import AsyncClient

from tests.factories import make_membership, make_organization, make_user
from trinol.core.authz.permissions import Role
from trinol.modules.identity.identity_verifier import VerifiedIdentity
from trinol.modules.identity.models import Membership, Organization


@dataclass(frozen=True, slots=True)
class LoggedInActor:
    organization: Organization
    membership: Membership
    csrf_token: str


async def login_as(client: AsyncClient, fake_verifier, db_session, *, role: Role) -> LoggedInActor:
    """Creates a fresh org + user + membership of the given role and logs
    them in via the fake Firebase exchange — shared by the security matrices,
    which all need the same "log in as an X in a brand-new org" setup."""
    org = await make_organization(db_session)
    user = await make_user(db_session, email=f"{role.value.lower()}-{org.id}@x.com")
    membership = await make_membership(db_session, organization=org, user=user, role=role)
    await db_session.commit()

    identity = VerifiedIdentity(
        firebase_uid=user.firebase_uid,
        email=user.email,
        email_verified=True,
        sign_in_provider="password",
        full_name=user.full_name,
        avatar_url=None,
    )
    token = f"tok-{membership.id}"
    fake_verifier.register(token, identity)
    response = await client.post("/api/v1/auth/session", json={"id_token": token})
    assert response.status_code == 200
    csrf_token = (await client.get("/api/v1/auth/session")).json()["csrf_token"]
    return LoggedInActor(organization=org, membership=membership, csrf_token=csrf_token)

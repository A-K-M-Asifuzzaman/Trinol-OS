from __future__ import annotations

from httpx import AsyncClient

from tests.factories import make_membership, make_organization, make_user
from trinol.modules.identity.identity_verifier import VerifiedIdentity
from trinol.modules.identity.models import Organization, User


async def _login(client: AsyncClient, fake_verifier, db_session) -> tuple[Organization, User, str]:
    """Creates an org+user+membership, logs in via the exchange endpoint, and
    returns (org, user, role) — the session cookie ends up in the client's
    own cookie jar automatically (httpx persists Set-Cookie across requests
    made through the same client)."""
    org = await make_organization(db_session)
    user = await make_user(db_session)
    membership = await make_membership(db_session, organization=org, user=user)
    await db_session.commit()

    identity = VerifiedIdentity(
        firebase_uid=user.firebase_uid,
        email=user.email,
        email_verified=True,
        sign_in_provider="password",
        full_name=user.full_name,
        avatar_url=None,
    )
    fake_verifier.register("tok", identity)
    response = await client.post("/api/v1/auth/session", json={"id_token": "tok"})
    assert response.status_code == 200
    return org, user, membership.role.value


async def test_get_session_returns_current_user_org_role(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    org, user, role = await _login(client, fake_verifier, db_session)

    response = await client.get("/api/v1/auth/session")

    assert response.status_code == 200
    body = response.json()
    assert body["user_id"] == str(user.id)
    assert body["organization_id"] == str(org.id)
    assert body["role"] == role
    assert body["csrf_token"]


async def test_get_session_without_cookie_returns_401(client: AsyncClient) -> None:
    response = await client.get("/api/v1/auth/session")
    assert response.status_code == 401


async def test_logout_revokes_the_session(client: AsyncClient, fake_verifier, db_session) -> None:
    await _login(client, fake_verifier, db_session)
    stale_cookie = client.cookies.get("trinol_session")
    csrf_token = (await client.get("/api/v1/auth/session")).json()["csrf_token"]

    response = await client.delete("/api/v1/auth/session", headers={"X-CSRF-Token": csrf_token})
    assert response.status_code == 204

    # Even re-presenting the exact stale cookie value fails now — this isn't
    # just "the client's cookie jar forgot it", the session row itself is
    # revoked (a second tab that never saw the logout would hit this path).
    client.cookies.set("trinol_session", stale_cookie)
    followup = await client.get("/api/v1/auth/session")
    assert followup.status_code == 401


async def test_logout_without_csrf_token_is_rejected(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    await _login(client, fake_verifier, db_session)

    response = await client.delete("/api/v1/auth/session")

    assert response.status_code == 403
    # Confirm nothing was actually revoked.
    assert (await client.get("/api/v1/auth/session")).status_code == 200


async def test_logout_everywhere_revokes_other_sessions_for_the_same_user(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    org = await make_organization(db_session)
    user = await make_user(db_session)
    await make_membership(db_session, organization=org, user=user)
    await db_session.commit()

    identity = VerifiedIdentity(
        firebase_uid=user.firebase_uid,
        email=user.email,
        email_verified=True,
        sign_in_provider="password",
        full_name=user.full_name,
        avatar_url=None,
    )
    fake_verifier.register("tok", identity)

    # Two independent logins for the same user (e.g. two devices/tabs).
    first_login = await client.post("/api/v1/auth/session", json={"id_token": "tok"})
    first_cookie = first_login.cookies.get("trinol_session")

    client.cookies.clear()
    second_login = await client.post("/api/v1/auth/session", json={"id_token": "tok"})
    assert second_login.cookies.get("trinol_session") != first_cookie

    csrf_token = (await client.get("/api/v1/auth/session")).json()["csrf_token"]
    response = await client.delete("/api/v1/auth/sessions", headers={"X-CSRF-Token": csrf_token})
    assert response.status_code == 204

    # The *other* session (first login) is revoked too, not just this one.
    client.cookies.set("trinol_session", first_cookie)
    other_session_check = await client.get("/api/v1/auth/session")
    assert other_session_check.status_code == 401

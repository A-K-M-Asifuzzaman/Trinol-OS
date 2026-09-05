from __future__ import annotations

from httpx import AsyncClient

from tests.factories import make_membership, make_organization, make_user
from trinol.modules.identity.identity_verifier import VerifiedIdentity

# AUTH.md §6 item 2: double-submit CSRF token, enforced by
# modules/identity/csrf.py's verify_csrf as a global FastAPI dependency.


async def _login(client: AsyncClient, fake_verifier, db_session) -> None:
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
    response = await client.post("/api/v1/auth/session", json={"id_token": "tok"})
    assert response.status_code == 200


async def test_missing_csrf_token_on_authenticated_mutation_is_rejected(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    await _login(client, fake_verifier, db_session)

    response = await client.delete("/api/v1/auth/session")

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


async def test_wrong_csrf_token_on_authenticated_mutation_is_rejected(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    await _login(client, fake_verifier, db_session)

    response = await client.delete(
        "/api/v1/auth/session", headers={"X-CSRF-Token": "not-the-real-token"}
    )

    assert response.status_code == 403


async def test_correct_csrf_token_is_accepted(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    await _login(client, fake_verifier, db_session)
    csrf_token = (await client.get("/api/v1/auth/session")).json()["csrf_token"]

    response = await client.delete("/api/v1/auth/session", headers={"X-CSRF-Token": csrf_token})

    assert response.status_code == 204


async def test_exchange_endpoint_is_exempt_from_csrf(client: AsyncClient, fake_verifier) -> None:
    # POST /api/v1/auth/session structurally can't carry a CSRF token — there
    # is no session yet at the point this request creates one. Already
    # exercised implicitly by every passing test_auth_exchange.py test (none
    # of them send X-CSRF-Token), asserted explicitly here.
    response = await client.post("/api/v1/auth/session", json={"id_token": "never-registered"})
    assert response.status_code == 401  # rejected by identity verification, not CSRF


async def test_no_session_cookie_defers_to_auth_not_csrf(client: AsyncClient) -> None:
    # An unsafe request with no session cookie at all has nothing to
    # double-submit against; verify_csrf skips it and get_current_session
    # rejects with 401, not verify_csrf with 403.
    response = await client.delete("/api/v1/auth/session")
    assert response.status_code == 401


async def test_safe_method_needs_no_csrf_token(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    await _login(client, fake_verifier, db_session)
    response = await client.get("/api/v1/auth/session")
    assert response.status_code == 200

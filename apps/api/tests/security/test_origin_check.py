from __future__ import annotations

from httpx import AsyncClient

# AUTH.md §6 item 1, enforced globally by OriginCheckMiddleware. Exercised
# here against POST /api/v1/auth/session — the only unsafe-method route that
# exists yet, and not coincidentally the one where the risk is sharpest:
# without this check, a cross-site page could trigger login-CSRF, silently
# establishing the victim's browser session under the attacker's account.
# Every future unsafe-method route gets this for free from the same
# middleware; TESTING.md §4's authn/authz matrices will exercise it per-route
# once more routes exist.


async def test_missing_origin_and_referer_is_rejected(client: AsyncClient, fake_verifier) -> None:
    headers = {"Origin": ""}
    response = await client.post(
        "/api/v1/auth/session", json={"id_token": "irrelevant"}, headers=headers
    )
    # httpx drops an empty header value rather than sending Origin: <empty>,
    # so this genuinely simulates "no Origin header at all" — no Referer is
    # set either, since the client fixture never sets one.
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "ORIGIN_MISMATCH"


async def test_mismatched_origin_is_rejected(client: AsyncClient, fake_verifier) -> None:
    response = await client.post(
        "/api/v1/auth/session",
        json={"id_token": "irrelevant"},
        headers={"Origin": "https://attacker.example"},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "ORIGIN_MISMATCH"


async def test_rejection_still_carries_a_request_id(client: AsyncClient, fake_verifier) -> None:
    # Regression test: middleware registration order is load-bearing here.
    # add_middleware's *last* call ends up outermost, so RequestIDMiddleware
    # must be added after OriginCheckMiddleware — otherwise a rejection is
    # built before the request_id context var is ever set, and this silently
    # comes back None (caught once already by running this for real, not by
    # inspection — see main.py's comment on the registration order).
    response = await client.post(
        "/api/v1/auth/session",
        json={"id_token": "irrelevant"},
        headers={"Origin": "https://attacker.example"},
    )
    assert response.status_code == 403
    assert response.json()["error"]["request_id"] is not None
    assert response.headers["x-request-id"] == response.json()["error"]["request_id"]


async def test_referer_fallback_is_accepted_when_origin_absent(
    client: AsyncClient, fake_verifier
) -> None:
    # No Origin header at all, but a Referer whose origin matches — the
    # documented fallback (AUTH.md §6 item 1). Still gets to real request
    # handling: an unregistered token, so 401, not 403 — proves the origin
    # check passed and let the request through.
    response = await client.post(
        "/api/v1/auth/session",
        json={"id_token": "irrelevant"},
        headers={"Origin": "", "Referer": "http://localhost:3000/login"},
    )
    assert response.status_code == 401


async def test_safe_method_is_not_checked() -> None:
    # GET isn't in the unsafe-method set; no Origin header needed. There's no
    # GET /api/v1/auth/session route yet (Stage 5), so /health stands in as
    # any safe-method route.
    from httpx import ASGITransport

    from trinol.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as anonymous_client:
        response = await anonymous_client.get("/health")
    assert response.status_code == 200

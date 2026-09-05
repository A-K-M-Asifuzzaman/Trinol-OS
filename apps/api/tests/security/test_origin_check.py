from __future__ import annotations

from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient

from trinol.core.security import origin_check

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


def test_contact_path_falls_back_to_app_origin_when_unconfigured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SECURITY.md §5's exception only activates once PUBLIC_CONTACT_ORIGIN is
    actually set (Phase 3). Until then this path behaves like any other —
    strict APP_ORIGIN only — which matters today since it doesn't correspond
    to a real route yet."""
    fake_settings = SimpleNamespace(app_origin="http://localhost:3000", public_contact_origin=None)
    monkeypatch.setattr(origin_check, "get_settings", lambda: fake_settings)

    assert origin_check._allowed_origin_for("/api/public/contact") == "http://localhost:3000"


def test_contact_path_allows_its_configured_origin(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_settings = SimpleNamespace(
        app_origin="http://localhost:3000",
        public_contact_origin="https://www.trinolit.com",
    )
    monkeypatch.setattr(origin_check, "get_settings", lambda: fake_settings)

    assert origin_check._allowed_origin_for("/api/public/contact") == "https://www.trinolit.com"
    # Every other path is unaffected — still strict APP_ORIGIN, even with
    # PUBLIC_CONTACT_ORIGIN configured.
    assert origin_check._allowed_origin_for("/api/v1/auth/session") == "http://localhost:3000"


async def test_safe_method_is_not_checked() -> None:
    # GET isn't in the unsafe-method set; no Origin header needed. There's no
    # GET /api/v1/auth/session route yet (Stage 5), so /health stands in as
    # any safe-method route.
    from trinol.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as anonymous_client:
        response = await anonymous_client.get("/health")
    assert response.status_code == 200

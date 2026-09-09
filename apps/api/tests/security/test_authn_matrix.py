from __future__ import annotations

import uuid

import pytest
from fastapi.routing import APIRoute
from httpx import AsyncClient

from trinol.core.authz.startup_audit import iter_api_routes
from trinol.main import app

# TESTING.md §4.1: every non-public route without a session -> 401.
#
# @public (core/authz/require.py) means "no Permission gate", not "no auth"
# — self-service routes like logout are @public but still require a valid
# session (get_current_session). The truly unauthenticated routes are this
# explicit, short list; every other registered route — @public or not —
# must 401 without a session cookie.
_TRULY_PUBLIC_ROUTES: frozenset[tuple[str, str]] = frozenset(
    {
        ("POST", "/api/v1/auth/session"),
        ("GET", "/api/v1/invitations/{token}"),
        ("GET", "/health"),
        ("GET", "/ready"),
        # Phase 3 Stage 6: the one genuinely unauthenticated write
        # (SECURITY.md §5) — needs its own dedicated coverage in
        # test_contact.py, not this generic test. A bare client.request
        # here sends the default app_origin header, which OriginCheckMiddleware
        # rejects with 403 the moment PUBLIC_CONTACT_ORIGIN is configured to
        # something else (as it already is in this env's .env) — 403 before
        # any auth check runs, so this test's 401 assertion would never even
        # be a meaningful check for this route either way.
        ("POST", "/api/public/contact"),
    }
)

_DUMMY_UUID = str(uuid.uuid4())


def _all_live_routes() -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for route in iter_api_routes(app):
        if not isinstance(route, APIRoute):
            continue
        for method in route.methods or set():
            if method in ("HEAD", "OPTIONS"):
                continue
            pairs.append((method, route.path))
    return pairs


def _routes_requiring_a_session() -> list[tuple[str, str]]:
    return [pair for pair in _all_live_routes() if pair not in _TRULY_PUBLIC_ROUTES]


def test_truly_public_routes_are_still_registered() -> None:
    """Guards the exclusion list above against drift — if one of these
    routes were ever renamed or removed, this fails instead of the
    exclusion silently covering nothing (and the route below quietly
    stopping being exercised by this matrix at all)."""
    live = set(_all_live_routes())
    missing = _TRULY_PUBLIC_ROUTES - live
    assert not missing, f"Route(s) no longer registered: {sorted(missing)}"


@pytest.mark.parametrize("method,path", _routes_requiring_a_session())
async def test_route_without_session_returns_401(
    client: AsyncClient, method: str, path: str
) -> None:
    resolved_path = path.replace("{membership_id}", _DUMMY_UUID)
    response = await client.request(method, resolved_path)
    assert response.status_code == 401, f"{method} {path} returned {response.status_code}"

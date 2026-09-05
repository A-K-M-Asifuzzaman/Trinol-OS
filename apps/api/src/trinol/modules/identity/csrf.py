from __future__ import annotations

import hashlib
import secrets

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from trinol.core.db.engine import get_db_session
from trinol.core.deps import get_settings
from trinol.core.errors import ForbiddenError
from trinol.modules.identity.services.session_service import get_session_by_token_hash

_UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

# POST /api/v1/auth/session has its own dedicated protection
# (core/security/origin_check.py) and is structurally exempt from this one:
# the double-submit token requires echoing a csrf_token from a session that
# doesn't exist yet at the point this exact request creates one.
_EXEMPT = frozenset({("POST", "/api/v1/auth/session")})


async def verify_csrf(request: Request, db: AsyncSession = Depends(get_db_session)) -> None:
    """AUTH.md §6 item 2. Registered as a FastAPI *global* dependency
    (`FastAPI(dependencies=[...])` in main.py), not raw ASGI middleware like
    core/security/origin_check.py — deliberately, so `Depends(get_db_session)`
    here respects the same `app.dependency_overrides` tests already rely on.
    It still can't be forgotten by a new route: global dependencies run on
    every path operation, not just ones that opt in.

    Lives in the identity module, not core/security, despite being a
    cross-cutting security check: unlike the origin check (pure header/config
    inspection, no business-module knowledge), this one is fundamentally
    coupled to session lookup — an identity concern, not a foundational one.

    Skipped for any request with no session cookie at all — nothing to
    double-submit against, and that request is either unauthenticated (fine)
    or will separately fail whatever auth dependency the route declares.
    Skipped for an unknown/invalid session cookie for the same reason: that's
    get_current_session's problem, not this one's.
    """
    if request.method not in _UNSAFE_METHODS:
        return
    if (request.method, request.url.path) in _EXEMPT:
        return

    settings = get_settings()
    cookie_value = request.cookies.get(settings.session_cookie_name)
    if cookie_value is None:
        return

    token_hash = hashlib.sha256(cookie_value.encode()).hexdigest()
    session = await get_session_by_token_hash(db, token_hash)
    if session is None:
        return

    csrf_header = request.headers.get("x-csrf-token")
    if csrf_header is None or not secrets.compare_digest(session.csrf_token, csrf_header):
        raise ForbiddenError("Invalid or missing CSRF token")

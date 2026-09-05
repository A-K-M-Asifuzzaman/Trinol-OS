from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from starlette.responses import JSONResponse

from trinol.core.deps import get_settings
from trinol.core.request_id import get_request_id

_UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

# SECURITY.md §5: the one documented exception, and specifically for POST —
# "POST /api/public/contact", not any unsafe method at that path. A plain
# single-origin check would reject trinolit.com's own contact form, which by
# design POSTs from a different origin than the app itself. Not a general
# per-path allowlist — there is exactly one known exception; if a second one
# is ever needed, that is the time to generalize this, not before (YAGNI).
_PUBLIC_CONTACT_METHOD = "POST"
_PUBLIC_CONTACT_PATH = "/api/public/contact"


def _origin_of(url: str) -> str | None:
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return None
    return f"{parsed.scheme}://{parsed.netloc}"


def _allowed_origin_for(method: str, path: str) -> str | None:
    settings = get_settings()
    is_contact_exception = (
        method == _PUBLIC_CONTACT_METHOD
        and path == _PUBLIC_CONTACT_PATH
        and settings.public_contact_origin
    )
    if is_contact_exception:
        return settings.public_contact_origin
    return settings.app_origin


class OriginCheckMiddleware:
    """AUTH.md §6 item 1, applied globally so a new route can't forget it —
    including POST /api/v1/auth/session itself. That endpoint mints a
    session, so without this check a cross-site page could trigger
    login-CSRF: silently establishing the *victim's* browser session under
    the *attacker's* account, no cookie or credential theft required. The
    double-submit CSRF token (AUTH.md §6 item 2) is a separate, later Stage 5
    piece — it structurally can't cover this endpoint anyway, since it
    requires echoing a csrf_hash from a session that doesn't exist yet at
    the point this request creates one.

    Pure ASGI, not BaseHTTPMiddleware — see request_id.py's docstring for why
    that distinction matters for anything that can short-circuit a response.
    Registered around RequestIDMiddleware (main.py) so get_request_id() is
    already set when a rejection response is built here.
    """

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] != "http" or scope["method"] not in _UNSAFE_METHODS:
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers") or [])
        origin_header = headers.get(b"origin")
        referer_header = headers.get(b"referer")

        candidate = _origin_of(origin_header.decode()) if origin_header else None
        if candidate is None and referer_header:
            candidate = _origin_of(referer_header.decode())

        if candidate is None or candidate != _allowed_origin_for(scope["method"], scope["path"]):
            response = JSONResponse(
                {
                    "error": {
                        "code": "ORIGIN_MISMATCH",
                        "message": "Request origin is not permitted",
                        "request_id": get_request_id(),
                        "details": {},
                    }
                },
                status_code=403,
            )
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)

from __future__ import annotations

from typing import Any

from starlette.responses import JSONResponse

from trinol.core.request_id import get_request_id

# SECURITY.md §5: 8 KiB cap for POST /api/public/contact specifically, not a
# global limit — no other route in the app is reachable by an unauthenticated
# caller, so no other route needs this.
_CAPPED_METHOD = "POST"
_CAPPED_PATH = "/api/public/contact"
_MAX_BODY_BYTES = 8 * 1024


class BodySizeCapMiddleware:
    """Pure ASGI, not a FastAPI route dependency — proven directly (not
    assumed) that a dependency runs too late: FastAPI reads and JSON-decodes
    the request body as part of resolving the endpoint's own body parameter,
    and for a *malformed* body that decode fails before any dependency
    (route-level or not) ever runs at all, short-circuiting straight to a
    422. A route-level Depends(...) can only ever catch a well-formed-but-
    oversized body, not the oversized-garbage case SECURITY.md §5 actually
    cares about most for an unauthenticated endpoint. Registered in main.py
    *inside* OriginCheckMiddleware (added before it, so it ends up innermost)
    so an origin-mismatched request is rejected without ever touching the
    body at all.

    Buffers and replays: reads the body once, checking cumulative size as
    each chunk arrives so an oversized upload is rejected without buffering
    unboundedly past the cap; a request within the cap is replayed to the
    inner app via a synthetic `receive` returning the buffered bytes as one
    message, so FastAPI's own body reading downstream sees the exact same
    stream it would have seen without this middleware in front of it.
    """

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if (
            scope["type"] != "http"
            or scope["method"] != _CAPPED_METHOD
            or scope["path"] != _CAPPED_PATH
        ):
            await self.app(scope, receive, send)
            return

        chunks: list[bytes] = []
        total = 0
        while True:
            message = await receive()
            if message["type"] != "http.request":
                break
            chunk = message.get("body", b"")
            total += len(chunk)
            if total > _MAX_BODY_BYTES:
                response = JSONResponse(
                    {
                        "error": {
                            "code": "PAYLOAD_TOO_LARGE",
                            "message": "Request body exceeds the 8 KiB limit",
                            "request_id": get_request_id(),
                            "details": {},
                        }
                    },
                    status_code=413,
                )
                await response(scope, receive, send)
                return
            chunks.append(chunk)
            if not message.get("more_body", False):
                break

        buffered = b"".join(chunks)
        replayed = False

        async def _replay_receive() -> Any:
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": buffered, "more_body": False}
            return await receive()

        await self.app(scope, _replay_receive, send)

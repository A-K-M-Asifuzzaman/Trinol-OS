from __future__ import annotations

from contextvars import ContextVar
from typing import Any

from trinol.core.ids import uuid7

REQUEST_ID_HEADER = "x-request-id"
_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)


def get_request_id() -> str | None:
    """Read by core/logging.py and core/errors.py to stamp the current request."""
    return _request_id.get()


class RequestIDMiddleware:
    """Pure ASGI middleware, deliberately not `BaseHTTPMiddleware`.

    `BaseHTTPMiddleware`'s `call_next` streams the inner app's response through
    a task group; when a route raises an exception FastAPI has no
    `ExceptionMiddleware`-registered handler for (i.e. a bare `Exception`,
    handled instead by Starlette's outer `ServerErrorMiddleware`), that
    buffering causes the exception to propagate as a raised exception with no
    response ever sent, instead of the JSON envelope `errors.py` registers for
    `Exception`. A thin raw-ASGI middleware has no such buffering — it just
    wraps `send` — so exceptions and their handlers behave exactly as FastAPI
    documents.
    """

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers") or [])
        incoming = headers.get(REQUEST_ID_HEADER.encode())
        request_id = incoming.decode() if incoming else str(uuid7())
        token = _request_id.set(request_id)

        async def send_wrapper(message: Any) -> None:
            if message["type"] == "http.response.start":
                message = dict(message)
                message["headers"] = [
                    *message.get("headers", []),
                    (REQUEST_ID_HEADER.encode(), request_id.encode()),
                ]
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            _request_id.reset(token)

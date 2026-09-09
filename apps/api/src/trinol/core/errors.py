from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from trinol.core.request_id import get_request_id

logger = logging.getLogger(__name__)


class AppError(Exception):
    """Base for errors that map to the error envelope (ARCHITECTURE.md §6)."""

    status_code: int = status.HTTP_400_BAD_REQUEST
    code: str = "BAD_REQUEST"

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class UnauthorizedError(AppError):
    status_code = status.HTTP_401_UNAUTHORIZED
    code = "UNAUTHORIZED"


class ForbiddenError(AppError):
    status_code = status.HTTP_403_FORBIDDEN
    code = "FORBIDDEN"


class NotFoundError(AppError):
    """Also used for cross-org resources — 404, never 403 (ADR-0003)."""

    status_code = status.HTTP_404_NOT_FOUND
    code = "NOT_FOUND"


class ConflictError(AppError):
    status_code = status.HTTP_409_CONFLICT
    code = "CONFLICT"


class UnprocessableEntityError(AppError):
    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    code = "VALIDATION_ERROR"


class RateLimitedError(AppError):
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    code = "RATE_LIMITED"


def _envelope(code: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "error": {
            "code": code,
            "message": message,
            "request_id": get_request_id(),
            "details": details or {},
        }
    }


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            _envelope(exc.code, exc.message, exc.details), status_code=exc.status_code
        )

    @app.exception_handler(RequestValidationError)
    async def _handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        details = {"errors": jsonable_encoder(exc.errors())}
        return JSONResponse(
            _envelope("VALIDATION_ERROR", "Request validation failed", details),
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )

    @app.exception_handler(StarletteHTTPException)
    async def _handle_http_exception(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        return JSONResponse(
            _envelope(f"HTTP_{exc.status_code}", str(exc.detail)),
            status_code=exc.status_code,
        )

    @app.exception_handler(Exception)
    async def _handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled exception", extra={"request_id": get_request_id()})
        return JSONResponse(
            _envelope("INTERNAL_ERROR", "An unexpected error occurred"),
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

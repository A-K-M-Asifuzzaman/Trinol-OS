from __future__ import annotations

from pathlib import Path

from alembic.config import Config as AlembicConfig
from alembic.script import ScriptDirectory
from fastapi import Depends, FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import text

from trinol.core.db.engine import get_engine
from trinol.core.db.org_session import register_org_scope_guard
from trinol.core.deps import get_settings
from trinol.core.errors import register_exception_handlers
from trinol.core.logging import configure_logging
from trinol.core.request_id import RequestIDMiddleware
from trinol.core.security.origin_check import OriginCheckMiddleware
from trinol.modules.identity.csrf import verify_csrf
from trinol.modules.identity.routes.auth import router as auth_router

_ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"


def _alembic_head() -> str | None:
    config = AlembicConfig(str(_ALEMBIC_INI))
    return ScriptDirectory.from_config(config).get_current_head()


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging("DEBUG" if settings.app_env == "local" else "INFO")
    register_org_scope_guard()

    # dependencies=: a global FastAPI dependency, applied to every route
    # (including ones from include_router below) — so a new route can't
    # forget CSRF verification, same intent as the ASGI middleware for the
    # origin check, just a different mechanism (AUTH.md §6).
    app = FastAPI(title="Trinol OS API", version="0.1.0", dependencies=[Depends(verify_csrf)])
    # add_middleware: the *last* one added ends up outermost. RequestIDMiddleware
    # must wrap OriginCheckMiddleware (not the reverse) so get_request_id()
    # is already set by the time a rejection response is built — verified
    # empirically, not assumed; this ordering is load-bearing.
    app.add_middleware(OriginCheckMiddleware)
    app.add_middleware(RequestIDMiddleware)
    register_exception_handlers(app)
    app.include_router(auth_router)

    @app.get("/health", tags=["meta"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/ready", tags=["meta"])
    async def ready() -> JSONResponse:
        try:
            async with get_engine().connect() as connection:
                result = await connection.execute(text("SELECT version_num FROM alembic_version"))
                current_revision = result.scalar_one_or_none()
        except Exception:
            return JSONResponse({"status": "not_ready", "reason": "database unreachable"}, 503)

        if current_revision != _alembic_head():
            return JSONResponse({"status": "not_ready", "reason": "migrations not at head"}, 503)
        return JSONResponse({"status": "ok"})

    return app


app = create_app()

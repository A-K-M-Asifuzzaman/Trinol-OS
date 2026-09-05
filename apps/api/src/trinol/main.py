from __future__ import annotations

from pathlib import Path

from alembic.config import Config as AlembicConfig
from alembic.script import ScriptDirectory
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from trinol.core.db.org_session import register_org_scope_guard
from trinol.core.deps import get_settings
from trinol.core.errors import register_exception_handlers
from trinol.core.logging import configure_logging
from trinol.core.request_id import RequestIDMiddleware

_ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"


def _alembic_head() -> str | None:
    config = AlembicConfig(str(_ALEMBIC_INI))
    return ScriptDirectory.from_config(config).get_current_head()


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging("DEBUG" if settings.app_env == "local" else "INFO")
    register_org_scope_guard()

    app = FastAPI(title="Trinol OS API", version="0.1.0")
    app.add_middleware(RequestIDMiddleware)
    register_exception_handlers(app)
    app.state.engine = create_async_engine(settings.database_url)

    @app.get("/health", tags=["meta"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/ready", tags=["meta"])
    async def ready() -> JSONResponse:
        try:
            async with app.state.engine.connect() as connection:
                result = await connection.execute(text("SELECT version_num FROM alembic_version"))
                current_revision = result.scalar_one_or_none()
        except Exception:
            return JSONResponse({"status": "not_ready", "reason": "database unreachable"}, 503)

        if current_revision != _alembic_head():
            return JSONResponse({"status": "not_ready", "reason": "migrations not at head"}, 503)
        return JSONResponse({"status": "ok"})

    return app


app = create_app()

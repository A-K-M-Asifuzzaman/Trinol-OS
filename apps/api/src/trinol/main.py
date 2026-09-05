from __future__ import annotations

from fastapi import FastAPI

from trinol.core.deps import get_settings
from trinol.core.errors import register_exception_handlers
from trinol.core.logging import configure_logging
from trinol.core.request_id import RequestIDMiddleware


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging("DEBUG" if settings.app_env == "local" else "INFO")

    app = FastAPI(title="Trinol OS API", version="0.1.0")
    app.add_middleware(RequestIDMiddleware)
    register_exception_handlers(app)

    @app.get("/health", tags=["meta"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    # /ready (DB reachable, migrations at head) lands in Stage 3 once there's
    # a database to check against — see docs/architecture/DEPLOYMENT.md §8.

    return app


app = create_app()

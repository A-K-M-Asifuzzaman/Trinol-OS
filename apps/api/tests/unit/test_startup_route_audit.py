from __future__ import annotations

import pytest
from fastapi import APIRouter, Depends, FastAPI

from trinol.core.authz.permissions import Permission
from trinol.core.authz.require import public, require
from trinol.core.authz.startup_audit import audit_routes


def test_unguarded_route_fails_the_audit() -> None:
    app = FastAPI()

    @app.get("/unguarded")
    async def unguarded() -> dict[str, str]:
        return {}

    with pytest.raises(RuntimeError, match="unguarded"):
        audit_routes(app)


def test_public_route_passes() -> None:
    app = FastAPI()

    @app.get("/ok")
    @public
    async def ok() -> dict[str, str]:
        return {}

    audit_routes(app)  # does not raise


def test_route_with_require_dependency_passes() -> None:
    app = FastAPI()

    @app.get("/ok", dependencies=[Depends(require(Permission.TEAM_READ))])
    async def ok() -> dict[str, str]:
        return {}

    audit_routes(app)  # does not raise


def test_unguarded_route_inside_an_included_router_is_still_caught() -> None:
    """Regression test: this FastAPI version wraps an include_router-added
    router in an internal _IncludedRouter object exposing .original_router,
    not a flat list in app.routes — confirmed by inspection while writing
    startup_audit.py. A naive `for route in app.routes` would silently miss
    every route added this way."""
    app = FastAPI()
    router = APIRouter()

    @router.get("/nested-unguarded")
    async def unguarded() -> dict[str, str]:
        return {}

    app.include_router(router)

    with pytest.raises(RuntimeError, match="nested-unguarded"):
        audit_routes(app)


def test_the_real_app_boots_without_raising() -> None:
    """The actual, meaningful check: every route registered by create_app()
    today is either @public or require()-gated. Importing trinol.main calls
    create_app(), which calls audit_routes() itself — if any current route
    were unguarded, this import would already have raised in every other
    test in the suite. Asserted explicitly here as its own test."""
    from trinol.main import app

    audit_routes(app)  # does not raise

from __future__ import annotations

from collections.abc import Iterator

from fastapi import FastAPI
from fastapi.routing import APIRoute, APIRouter

from trinol.core.authz.require import get_required_permission, is_public


def audit_routes(app: FastAPI) -> None:
    """RBAC.md §3: a route with no `require(...)` and no `@public` marker
    fails boot — the single most valuable guard in the system, turning
    "forgot to add authorization" into a boot failure instead of a
    vulnerability. Called once at the end of create_app(), after every route
    is registered.
    """
    unguarded = sorted({route.path for route in iter_api_routes(app) if not _is_guarded(route)})
    if unguarded:
        raise RuntimeError(
            "Route(s) with no require(...) permission and no @public marker: "
            f"{', '.join(unguarded)}. Add one or the other (RBAC.md §3)."
        )


def iter_api_routes(
    app_or_router: FastAPI | APIRouter, _seen: set[int] | None = None
) -> Iterator[APIRoute]:
    """Walks app.routes, recursing into include_router-added routers.

    This FastAPI version wraps an included router in an internal
    `_IncludedRouter` object exposing `.original_router` (a plain
    `APIRouter`), rather than flattening its routes directly into
    `app.routes` — confirmed by inspection, not assumed. Public (not
    underscore-prefixed): TESTING.md §4's security matrices also need to
    walk the live route table, rather than hand-maintaining a second list
    that could silently drift from what's actually registered.
    """
    seen = _seen if _seen is not None else set()
    for route in app_or_router.routes:
        if isinstance(route, APIRoute):
            yield route
        else:
            inner = getattr(route, "original_router", None)
            if inner is not None and id(inner) not in seen:
                seen.add(id(inner))
                yield from iter_api_routes(inner, seen)


def _is_guarded(route: APIRoute) -> bool:
    if is_public(route.endpoint):
        return True
    return any(
        dependency.dependency is not None
        and get_required_permission(dependency.dependency) is not None
        for dependency in route.dependencies
    )

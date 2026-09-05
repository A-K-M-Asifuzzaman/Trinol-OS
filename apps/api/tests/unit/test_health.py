from __future__ import annotations

from httpx import ASGITransport, AsyncClient

from trinol.main import app


async def test_health_ok() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_unhandled_exception_returns_error_envelope() -> None:
    @app.get("/__boom_test_only")
    async def boom() -> None:
        raise RuntimeError("kaboom")

    # Starlette's ServerErrorMiddleware sends our JSON response, then
    # re-raises the original exception so a real ASGI server can log/debug it
    # (uvicorn just logs and keeps the already-sent response; only the test
    # transport needs telling not to treat that as a broken request).
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/__boom_test_only")

    assert response.status_code == 500
    body = response.json()
    assert body["error"]["code"] == "INTERNAL_ERROR"
    assert "request_id" in body["error"]


async def test_ready_ok_when_migrated() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_request_id_header_echoed() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health", headers={"X-Request-Id": "test-req-123"})
    assert response.headers["X-Request-Id"] == "test-req-123"

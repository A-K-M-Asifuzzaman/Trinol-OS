from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from tests.fakes import FakeIdentityVerifier
from trinol.core.db.engine import get_db_session
from trinol.core.db.org_session import register_org_scope_guard
from trinol.core.deps import get_settings
from trinol.modules.identity.deps import get_identity_verifier

register_org_scope_guard()


@pytest.fixture(scope="session")
async def _connection() -> AsyncIterator[AsyncConnection]:
    """One engine/connection for the whole test session; every test runs in
    its own rolled-back transaction on it (TESTING.md §2) — migrations
    already ran via `alembic upgrade head` before pytest starts."""
    engine = create_async_engine(get_settings().database_url)
    async with engine.connect() as connection:
        yield connection
    await engine.dispose()


@pytest.fixture
async def db_session(_connection: AsyncConnection) -> AsyncIterator[AsyncSession]:
    transaction = await _connection.begin()
    # create_savepoint: service code under test calls session.commit() for
    # real (it's the transaction boundary, ARCHITECTURE.md §4) — that must
    # only release a SAVEPOINT, not this outer transaction, or the rollback
    # below would have nothing left to undo.
    session_factory = async_sessionmaker(
        bind=_connection, join_transaction_mode="create_savepoint", expire_on_commit=False
    )
    session = session_factory()
    try:
        yield session
    finally:
        await session.close()
        await transaction.rollback()


@pytest.fixture
async def client(db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    """Every route test uses this, not a bare ASGITransport(app=app) — it
    overrides get_db_session so requests run inside this test's own
    transaction-wrapped session and roll back with everything else.

    Default Origin header matches settings.app_origin: OriginCheckMiddleware
    (AUTH.md §6) rejects any unsafe method without one, same as a real
    browser request from our own frontend would always include. A test that
    specifically exercises the rejection overrides or removes it per-request.
    """
    from trinol.main import app

    async def _override_get_db_session() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_db_session] = _override_get_db_session
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(
            transport=transport,
            base_url="http://test",
            headers={"Origin": get_settings().app_origin},
        ) as async_client:
            yield async_client
    finally:
        app.dependency_overrides.pop(get_db_session, None)


@pytest.fixture
def fake_verifier() -> FakeIdentityVerifier:
    """Overrides get_identity_verifier for the duration of the test — no test
    anywhere in the suite calls real Firebase (ADR-0013)."""
    from trinol.main import app

    verifier = FakeIdentityVerifier()
    app.dependency_overrides[get_identity_verifier] = lambda: verifier
    try:
        yield verifier
    finally:
        app.dependency_overrides.pop(get_identity_verifier, None)

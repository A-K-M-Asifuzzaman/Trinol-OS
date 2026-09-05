from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from trinol.core.db.org_session import register_org_scope_guard
from trinol.core.deps import get_settings

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

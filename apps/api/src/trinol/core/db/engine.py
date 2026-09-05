from __future__ import annotations

from collections.abc import AsyncIterator
from functools import lru_cache

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from trinol.core.deps import get_settings


@lru_cache
def get_engine() -> AsyncEngine:
    """One engine for the whole process — shared by every request's session
    and by main.py's /ready check, not a separate pool each."""
    return create_async_engine(get_settings().database_url)


@lru_cache
def get_session_factory() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_engine(), expire_on_commit=False)


async def get_db_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: one AsyncSession per request. Overridden in
    integration tests with the transaction-wrapped `db_session` fixture
    (conftest.py) so each test rolls back cleanly."""
    async with get_session_factory()() as session:
        yield session

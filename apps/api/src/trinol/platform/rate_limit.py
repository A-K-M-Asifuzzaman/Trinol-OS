from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from trinol.core.errors import RateLimitedError

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def _window_start(now: datetime, window: timedelta) -> datetime:
    elapsed_windows = (now - _EPOCH) // window
    return _EPOCH + elapsed_windows * window


async def check_rate_limit(
    session: AsyncSession, *, key: str, window: timedelta, limit: int
) -> None:
    """Atomic fixed-window limiter (ADR-0010): one INSERT ... ON CONFLICT DO
    UPDATE, never a separate read-increment-write — that would race under
    concurrent requests for the same key. Raises RateLimitedError once a
    window's count exceeds `limit`; every call increments first, including
    ones that end up rejected, so an attacker can't probe for the limit for
    free.

    Caller's responsibility, not this function's: commit immediately after
    calling this if the surrounding transaction might later roll back for an
    unrelated reason — the counter must survive that rollback, or a bad actor
    who's about to be rejected anyway (e.g. an invalid token) is never
    actually throttled.
    """
    now = datetime.now(UTC)
    window_start = _window_start(now, window)

    result = await session.execute(
        text(
            """
            INSERT INTO rate_limit_buckets (key, window_start, count)
            VALUES (:key, :window_start, 1)
            ON CONFLICT (key) DO UPDATE SET
                count = CASE
                    WHEN rate_limit_buckets.window_start = EXCLUDED.window_start
                    THEN rate_limit_buckets.count + 1
                    ELSE 1
                END,
                window_start = EXCLUDED.window_start
            RETURNING count
            """
        ),
        {"key": key, "window_start": window_start},
    )
    count = result.scalar_one()
    if count > limit:
        # int(window.total_seconds()): the fixed window's full length, not
        # the precise remaining time (this limiter doesn't track that) — a
        # deliberately conservative approximation, fine for a Retry-After
        # hint (SECURITY.md §5's public contact endpoint is the one caller
        # that reads this field today).
        raise RateLimitedError(
            f"Rate limit exceeded for {key}", retry_after_seconds=int(window.total_seconds())
        )

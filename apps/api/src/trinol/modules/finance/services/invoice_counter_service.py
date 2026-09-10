from __future__ import annotations

import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def next_invoice_number(db: AsyncSession, *, organization_id: uuid.UUID, year: int) -> str:
    """ADR-0007: `TRI-{year}-{seq:04d}`, sequence from an
    `invoice_counters(organization_id, year)` row, so two concurrent
    invoices in the same org/year can never compute the same number.

    One atomic `INSERT ... ON CONFLICT DO UPDATE ... RETURNING` — the same
    idiom `platform.rate_limit.check_rate_limit` already uses for its own
    atomic counter. This handles both 'first invoice this org/year' (the
    row doesn't exist yet) and 'increment an existing row' in a single
    round trip; Postgres itself serializes two concurrent callers via the
    upsert, rather than a separate `SELECT ... FOR UPDATE` needing its own
    bootstrap-insert-if-missing dance around a row that might not exist
    yet.
    """
    result = await db.execute(
        text(
            """
            INSERT INTO invoice_counters (organization_id, year, last_seq)
            VALUES (:organization_id, :year, 1)
            ON CONFLICT (organization_id, year) DO UPDATE SET
                last_seq = invoice_counters.last_seq + 1
            RETURNING last_seq
            """
        ),
        {"organization_id": organization_id, "year": year},
    )
    seq = result.scalar_one()
    return f"TRI-{year}-{seq:04d}"

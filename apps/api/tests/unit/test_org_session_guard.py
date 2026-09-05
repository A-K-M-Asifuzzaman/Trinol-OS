from __future__ import annotations

import pytest
from sqlalchemy import select

from trinol.core.db.org_session import OrgSession
from trinol.core.ids import uuid7
from trinol.modules.identity.models import Membership

pytestmark = pytest.mark.usefixtures("db_session")


async def test_org_session_select_includes_org_filter(db_session) -> None:
    org_session = OrgSession(db_session, organization_id=uuid7())
    stmt = org_session.select(Membership)
    assert "organization_id" in str(stmt.whereclause)


async def test_raw_select_on_org_scoped_table_without_filter_raises(db_session) -> None:
    # The guard fires regardless of how the statement was built — this is
    # deliberately a raw session.execute(), not OrgSession, to prove someone
    # bypassing OrgSession still gets caught (DATABASE.md §5 item 3).
    with pytest.raises(RuntimeError, match="organization_id"):
        await db_session.execute(select(Membership))


async def test_select_with_org_filter_is_allowed(db_session) -> None:
    org_id = uuid7()
    # Doesn't need to match a real row — the guard only checks the predicate
    # is present, not that it's correct (that's the isolation test matrix,
    # TESTING.md §4 item 3).
    stmt = select(Membership).where(Membership.organization_id == org_id)
    result = await db_session.execute(stmt)
    assert result.scalars().all() == []


async def test_unscoped_escape_hatch_bypasses_guard(db_session) -> None:
    stmt = OrgSession.unscoped(select(Membership))
    result = await db_session.execute(stmt)
    assert result.scalars().all() is not None

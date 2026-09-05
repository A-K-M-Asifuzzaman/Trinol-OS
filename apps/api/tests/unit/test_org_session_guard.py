from __future__ import annotations

import pytest
from sqlalchemy import delete, select, update

from trinol.core.db.org_session import OrgSession
from trinol.core.ids import uuid7
from trinol.modules.identity.models import Membership, MembershipStatus

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


async def test_raw_update_on_org_scoped_table_without_filter_raises(db_session) -> None:
    stmt = update(Membership).values(status=MembershipStatus.INACTIVE.value)
    with pytest.raises(RuntimeError, match="organization_id"):
        await db_session.execute(stmt)


async def test_raw_delete_on_org_scoped_table_without_filter_raises(db_session) -> None:
    with pytest.raises(RuntimeError, match="organization_id"):
        await db_session.execute(delete(Membership))


async def test_update_with_org_filter_is_allowed(db_session) -> None:
    org_id = uuid7()
    stmt = (
        update(Membership)
        .where(Membership.organization_id == org_id)
        .values(status=MembershipStatus.INACTIVE.value)
    )
    result = await db_session.execute(stmt)
    assert result.rowcount == 0


async def test_add_stamps_organization_id_when_unset(db_session) -> None:
    org_session = OrgSession(db_session, organization_id=uuid7())
    membership = Membership(user_id=uuid7(), role="MEMBER")
    org_session.add(membership)
    assert membership.organization_id == org_session.organization_id


async def test_add_rejects_mismatched_organization_id(db_session) -> None:
    org_session = OrgSession(db_session, organization_id=uuid7())
    other_org_id = uuid7()
    membership = Membership(organization_id=other_org_id, user_id=uuid7(), role="MEMBER")
    with pytest.raises(ValueError, match="does not match"):
        org_session.add(membership)

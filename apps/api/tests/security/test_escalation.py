from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from dotenv import dotenv_values
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import create_async_engine

from tests.factories import make_membership, make_organization, make_user
from trinol.core.authz.permissions import Role
from trinol.core.config import _ENV_FILE
from trinol.core.db.engine import get_session_factory
from trinol.core.errors import ForbiddenError, NotFoundError
from trinol.core.ids import uuid7
from trinol.modules.identity.models import (
    Membership,
    MembershipStatus,
    Organization,
    Session,
    User,
)
from trinol.modules.identity.services.membership_service import change_role, remove_member
from trinol.platform.models import ActivityEvent

# RBAC.md §5's six escalation guards. #6 (activity events) is implemented in
# membership_service.py but asserted in tests/integration/test_activity_writer.py,
# not here.

pytestmark = pytest.mark.usefixtures("db_session")


async def _setup(db_session):
    org = await make_organization(db_session)
    owner_user = await make_user(db_session, email="owner@x.com")
    admin_user = await make_user(db_session, email="admin@x.com")
    manager_user = await make_user(db_session, email="manager@x.com")
    member_user = await make_user(db_session, email="member@x.com")
    owner = await make_membership(db_session, organization=org, user=owner_user, role=Role.OWNER)
    admin = await make_membership(db_session, organization=org, user=admin_user, role=Role.ADMIN)
    manager = await make_membership(
        db_session, organization=org, user=manager_user, role=Role.MANAGER
    )
    member = await make_membership(db_session, organization=org, user=member_user, role=Role.MEMBER)
    await db_session.commit()
    return org, owner, admin, manager, member


async def test_guard_1_cannot_change_own_role(db_session) -> None:
    org, owner, admin, manager, member = await _setup(db_session)
    with pytest.raises(ForbiddenError, match="own role"):
        await change_role(
            db_session,
            organization_id=org.id,
            actor=admin,
            target_membership_id=admin.id,
            new_role=Role.MANAGER,
        )


async def test_guard_1_cannot_remove_self(db_session) -> None:
    org, owner, admin, manager, member = await _setup(db_session)
    with pytest.raises(ForbiddenError, match="cannot remove yourself"):
        await remove_member(
            db_session, organization_id=org.id, actor=admin, target_membership_id=admin.id
        )


async def test_guard_2_admin_cannot_grant_admin(db_session) -> None:
    org, owner, admin, manager, member = await _setup(db_session)
    with pytest.raises(ForbiddenError, match="Only an OWNER"):
        await change_role(
            db_session,
            organization_id=org.id,
            actor=admin,
            target_membership_id=manager.id,
            new_role=Role.ADMIN,
        )


async def test_guard_2_owner_may_grant_admin(db_session) -> None:
    org, owner, admin, manager, member = await _setup(db_session)
    updated = await change_role(
        db_session,
        organization_id=org.id,
        actor=owner,
        target_membership_id=manager.id,
        new_role=Role.ADMIN,
    )
    assert updated.role == Role.ADMIN


async def test_guard_3_admin_cannot_modify_owner(db_session) -> None:
    org, owner, admin, manager, member = await _setup(db_session)
    with pytest.raises(ForbiddenError, match="may not modify"):
        await change_role(
            db_session,
            organization_id=org.id,
            actor=admin,
            target_membership_id=owner.id,
            new_role=Role.MANAGER,
        )


async def test_guard_3_admin_cannot_modify_another_admin(db_session) -> None:
    org, owner, admin, manager, member = await _setup(db_session)
    other_admin = await make_membership(
        db_session,
        organization=org,
        user=await make_user(db_session, email="admin2@x.com"),
        role=Role.ADMIN,
    )
    await db_session.commit()
    with pytest.raises(ForbiddenError, match="may not modify"):
        await change_role(
            db_session,
            organization_id=org.id,
            actor=admin,
            target_membership_id=other_admin.id,
            new_role=Role.MANAGER,
        )


async def test_guard_3_admin_cannot_remove_owner(db_session) -> None:
    org, owner, admin, manager, member = await _setup(db_session)
    with pytest.raises(ForbiddenError, match="may not remove"):
        await remove_member(
            db_session, organization_id=org.id, actor=admin, target_membership_id=owner.id
        )


async def test_guard_4_demoting_one_of_two_owners_is_allowed(db_session) -> None:
    org, owner, admin, manager, member = await _setup(db_session)
    second_owner = await make_membership(
        db_session,
        organization=org,
        user=await make_user(db_session, email="owner2@x.com"),
        role=Role.OWNER,
    )
    await db_session.commit()

    updated = await change_role(
        db_session,
        organization_id=org.id,
        actor=owner,
        target_membership_id=second_owner.id,
        new_role=Role.ADMIN,
    )
    assert updated.role == Role.ADMIN


async def test_guard_5_role_change_revokes_target_sessions_in_this_org(db_session) -> None:
    org, owner, admin, manager, member = await _setup(db_session)
    now = datetime.now(UTC)
    session_row = Session(
        id=uuid7(),
        organization_id=org.id,
        user_id=manager.user_id,
        token_hash=f"th-{uuid7()}",
        csrf_token=f"ct-{uuid7()}",
        expires_at=now + timedelta(days=1),
        last_seen_at=now,
    )
    db_session.add(session_row)
    await db_session.commit()

    await change_role(
        db_session,
        organization_id=org.id,
        actor=owner,
        target_membership_id=manager.id,
        new_role=Role.ADMIN,
    )

    refreshed = (
        await db_session.execute(
            select(Session).where(Session.organization_id == org.id, Session.id == session_row.id)
        )
    ).scalar_one()
    assert refreshed.revoked_at is not None


async def test_target_in_another_organization_is_not_found(db_session) -> None:
    """RBAC.md §4: a cross-org target is 404, not 403 — the query is already
    org-scoped, so a wrong-org id lands here indistinguishably from a
    genuinely missing one."""
    org, owner, admin, manager, member = await _setup(db_session)
    other_org = await make_organization(db_session)
    other_owner = await make_membership(
        db_session,
        organization=other_org,
        user=await make_user(db_session, email="otherowner@x.com"),
        role=Role.OWNER,
    )
    await db_session.commit()

    with pytest.raises(NotFoundError):
        await change_role(
            db_session,
            organization_id=org.id,
            actor=owner,
            target_membership_id=other_owner.id,
            new_role=Role.ADMIN,
        )


async def test_actor_from_another_organization_cannot_change_role(db_session) -> None:
    """A caller bug (organization_id not actually derived from actor's own
    session) must not let an OWNER of one org operate on another org's
    memberships just because organization_id was passed as that other org."""
    org, owner, admin, manager, member = await _setup(db_session)
    other_org = await make_organization(db_session)
    other_org_owner = await make_membership(
        db_session,
        organization=other_org,
        user=await make_user(db_session, email="otherorgowner@x.com"),
        role=Role.OWNER,
    )
    await db_session.commit()

    with pytest.raises(ForbiddenError, match="does not belong to this organization"):
        await change_role(
            db_session,
            organization_id=org.id,
            actor=other_org_owner,
            target_membership_id=manager.id,
            new_role=Role.ADMIN,
        )


async def test_actor_from_another_organization_cannot_remove_member(db_session) -> None:
    org, owner, admin, manager, member = await _setup(db_session)
    other_org = await make_organization(db_session)
    other_org_owner = await make_membership(
        db_session,
        organization=other_org,
        user=await make_user(db_session, email="otherorgowner2@x.com"),
        role=Role.OWNER,
    )
    await db_session.commit()

    with pytest.raises(ForbiddenError, match="does not belong to this organization"):
        await remove_member(
            db_session,
            organization_id=org.id,
            actor=other_org_owner,
            target_membership_id=manager.id,
        )


async def test_guard_4_concurrent_demotion_of_both_owners_only_one_succeeds() -> None:
    """The scenario the FOR UPDATE lock (guard 4) exists for: two owners try
    to demote each other at the same moment. If both succeeded, the org
    would end up with zero owners. This genuinely needs two independent DB
    connections — not two SAVEPOINTs sharing the suite's one rolled-back
    transaction — since the point is Postgres serializing two real
    concurrent transactions on the same locked row. Real commits, cleaned up
    explicitly at the end rather than relying on the shared fixture's
    rollback (which never sees this test's data in the first place)."""
    session_factory = get_session_factory()

    setup_session = session_factory()
    try:
        org = await make_organization(setup_session)
        user_a = await make_user(setup_session, email=f"concurrent-a-{org.id}@x.com")
        user_b = await make_user(setup_session, email=f"concurrent-b-{org.id}@x.com")
        owner_a = await make_membership(
            setup_session, organization=org, user=user_a, role=Role.OWNER
        )
        owner_b = await make_membership(
            setup_session, organization=org, user=user_b, role=Role.OWNER
        )
        await setup_session.commit()
        org_id, owner_a_id, owner_b_id = org.id, owner_a.id, owner_b.id
        user_a_id, user_b_id = user_a.id, user_b.id
    finally:
        await setup_session.close()

    session_1 = session_factory()
    session_2 = session_factory()
    try:
        actor_a = (
            await session_1.execute(
                select(Membership).where(
                    Membership.organization_id == org_id, Membership.id == owner_a_id
                )
            )
        ).scalar_one()
        actor_b = (
            await session_2.execute(
                select(Membership).where(
                    Membership.organization_id == org_id, Membership.id == owner_b_id
                )
            )
        ).scalar_one()

        results = await asyncio.gather(
            change_role(
                session_1,
                organization_id=org_id,
                actor=actor_a,
                target_membership_id=owner_b_id,
                new_role=Role.ADMIN,
            ),
            change_role(
                session_2,
                organization_id=org_id,
                actor=actor_b,
                target_membership_id=owner_a_id,
                new_role=Role.ADMIN,
            ),
            return_exceptions=True,
        )

        successes = [r for r in results if not isinstance(r, Exception)]
        failures = [r for r in results if isinstance(r, Exception)]

        assert len(successes) == 1, f"expected exactly one success, got: {results}"
        assert len(failures) == 1
        assert isinstance(failures[0], ForbiddenError)

        remaining_owners = (
            (
                await session_1.execute(
                    select(Membership).where(
                        Membership.organization_id == org_id,
                        Membership.role == Role.OWNER,
                        Membership.status == MembershipStatus.ACTIVE,
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(remaining_owners) == 1, "the org must never end up with zero owners"
    finally:
        await session_1.close()
        await session_2.close()

        # trinol_app (get_session_factory's role) is REVOKEd from
        # UPDATE/DELETE on activity_events by design (ADR-0006 — "must be run
        # by a maintenance role, since the application role cannot delete.
        # That friction is the point."). The winning change_role call wrote a
        # real row there (guard 6), so cleanup needs the migrator role, same
        # as Alembic uses, for this one step only.
        migration_url = dotenv_values(_ENV_FILE)["DATABASE_MIGRATION_URL"]
        assert migration_url is not None
        migrator_engine = create_async_engine(migration_url)
        try:
            async with migrator_engine.begin() as conn:
                await conn.execute(
                    ActivityEvent.__table__.delete().where(ActivityEvent.organization_id == org_id)
                )
        finally:
            await migrator_engine.dispose()

        cleanup_session = session_factory()
        try:
            await cleanup_session.execute(
                delete(Membership).where(Membership.organization_id == org_id)
            )
            await cleanup_session.execute(delete(User).where(User.id.in_([user_a_id, user_b_id])))
            await cleanup_session.execute(delete(Organization).where(Organization.id == org_id))
            await cleanup_session.commit()
        finally:
            await cleanup_session.close()

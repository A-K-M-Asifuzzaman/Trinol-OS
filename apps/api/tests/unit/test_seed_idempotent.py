from __future__ import annotations

from sqlalchemy import delete, select

from trinol.core.db.engine import get_session_factory
from trinol.modules.identity.models import Membership, Organization, User
from trinol.scripts.seed import _ORG_SLUG, _SEED_USERS, seed

# Phase 1 plan, Stage 12 proof criterion: "make seed on a fresh DB produces
# the expected rows; re-running doesn't duplicate or error." seed() manages
# its own real session (it's a standalone CLI, not a request handler), so
# this can't use the transaction-rollback db_session fixture the rest of the
# suite relies on — same reasoning as test_escalation.py's concurrent-
# demotion test, and the same manual real-DB cleanup in a finally block.
#
# That cleanup only removes the org/users if THIS test is the one that
# created them: a developer may have already run `make seed` for real local
# use (ROADMAP.md's own verification sequence runs it before `make check`,
# which runs this suite) — the test proving idempotency must not silently
# delete their actual seeded data as a side effect.


async def test_seed_is_idempotent() -> None:
    session_factory = get_session_factory()
    async with session_factory() as db:
        pre_existing = (
            await db.execute(select(Organization).where(Organization.slug == _ORG_SLUG))
        ).scalar_one_or_none() is not None

    try:
        await seed()
        await seed()

        async with session_factory() as db:
            org_result = await db.execute(
                select(Organization).where(Organization.slug == _ORG_SLUG)
            )
            organizations = org_result.scalars().all()
            assert len(organizations) == 1, "re-running must not duplicate the organization"
            organization = organizations[0]

            membership_result = await db.execute(
                select(Membership).where(Membership.organization_id == organization.id)
            )
            assert len(membership_result.scalars().all()) == len(_SEED_USERS)

            user_result = await db.execute(
                select(User).where(User.email.in_([entry.email for entry in _SEED_USERS]))
            )
            assert len(user_result.scalars().all()) == len(_SEED_USERS)
    finally:
        if not pre_existing:
            async with session_factory() as db:
                org_result = await db.execute(
                    select(Organization).where(Organization.slug == _ORG_SLUG)
                )
                organization = org_result.scalar_one_or_none()
                if organization is not None:
                    await db.execute(
                        delete(Membership).where(Membership.organization_id == organization.id)
                    )
                    await db.execute(delete(Organization).where(Organization.id == organization.id))
                await db.execute(
                    delete(User).where(User.email.in_([entry.email for entry in _SEED_USERS]))
                )
                await db.commit()

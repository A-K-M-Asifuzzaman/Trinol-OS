from __future__ import annotations

import pytest

from tests.factories import make_membership, make_organization, make_user
from trinol.core.authz.permissions import Role
from trinol.core.errors import ForbiddenError, NotFoundError
from trinol.modules.identity.services.team_service import get_member, list_members


async def _setup(db_session):
    org = await make_organization(db_session)
    owner_user = await make_user(db_session, email="owner@x.com")
    member_user = await make_user(db_session, email="member@x.com")
    owner = await make_membership(db_session, organization=org, user=owner_user, role=Role.OWNER)
    member = await make_membership(db_session, organization=org, user=member_user, role=Role.MEMBER)
    await db_session.commit()
    return org, owner, member


async def test_list_members_returns_joined_user_fields(db_session) -> None:
    org, owner, member = await _setup(db_session)
    result = await list_members(db_session, organization_id=org.id, actor=member)
    assert result.total == 2
    by_role = {item.membership.role: item for item in result.items}
    assert by_role[Role.OWNER].user.email == "owner@x.com"
    assert by_role[Role.MEMBER].user.email == "member@x.com"


async def test_list_members_is_paginated(db_session) -> None:
    org, owner, member = await _setup(db_session)
    page = await list_members(db_session, organization_id=org.id, actor=member, limit=1, offset=0)
    assert len(page.items) == 1
    assert page.total == 2


async def test_get_member_returns_joined_user_fields(db_session) -> None:
    org, owner, member = await _setup(db_session)
    result = await get_member(
        db_session, organization_id=org.id, actor=member, membership_id=owner.id
    )
    assert result.user.email == "owner@x.com"
    assert result.membership.role == Role.OWNER


async def test_get_member_in_another_org_is_not_found(db_session) -> None:
    org, owner, member = await _setup(db_session)
    other_org = await make_organization(db_session)
    other_owner = await make_membership(
        db_session,
        organization=other_org,
        user=await make_user(db_session, email="otherowner@x.com"),
        role=Role.OWNER,
    )
    await db_session.commit()

    with pytest.raises(NotFoundError):
        await get_member(
            db_session, organization_id=org.id, actor=member, membership_id=other_owner.id
        )


async def test_actor_from_another_organization_cannot_list(db_session) -> None:
    org, owner, member = await _setup(db_session)
    other_org = await make_organization(db_session)
    other_owner = await make_membership(
        db_session,
        organization=other_org,
        user=await make_user(db_session, email="otherowner2@x.com"),
        role=Role.OWNER,
    )
    await db_session.commit()

    with pytest.raises(ForbiddenError, match="does not belong to this organization"):
        await list_members(db_session, organization_id=org.id, actor=other_owner)

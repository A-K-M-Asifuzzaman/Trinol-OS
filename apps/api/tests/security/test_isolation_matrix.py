from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.factories import make_membership, make_organization, make_user
from tests.helpers import login_as
from trinol.core.authz.permissions import Role

# TESTING.md §4.3: every org-scoped route, member of org B against a
# resource in org A -> 404, never 403 and never 200. Team routes only for
# now (see test_authz_matrix.py's matching note).

pytestmark = pytest.mark.usefixtures("db_session")


async def test_get_team_member_in_another_org_is_404(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    other_org = await make_organization(db_session)
    other_user = await make_user(db_session, email=f"other-{other_org.id}@x.com")
    other_membership = await make_membership(
        db_session, organization=other_org, user=other_user, role=Role.MEMBER
    )
    await db_session.commit()

    await login_as(client, fake_verifier, db_session, role=Role.ADMIN)

    response = await client.get(f"/api/v1/memberships/{other_membership.id}")
    assert response.status_code == 404


async def test_patch_team_member_in_another_org_is_404(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    other_org = await make_organization(db_session)
    other_user = await make_user(db_session, email=f"other2-{other_org.id}@x.com")
    other_membership = await make_membership(
        db_session, organization=other_org, user=other_user, role=Role.MEMBER
    )
    await db_session.commit()

    actor = await login_as(client, fake_verifier, db_session, role=Role.ADMIN)

    response = await client.patch(
        f"/api/v1/memberships/{other_membership.id}",
        json={"role": "MANAGER"},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == 404


async def test_list_team_never_leaks_another_orgs_members(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    other_org = await make_organization(db_session)
    other_user = await make_user(db_session, email=f"other3-{other_org.id}@x.com")
    await make_membership(db_session, organization=other_org, user=other_user, role=Role.MEMBER)
    await db_session.commit()

    await login_as(client, fake_verifier, db_session, role=Role.MEMBER)

    response = await client.get("/api/v1/memberships")
    assert response.status_code == 200
    emails = [member["email"] for member in response.json()["items"]]
    assert other_user.email not in emails

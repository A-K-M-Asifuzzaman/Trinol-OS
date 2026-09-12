from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

import pytest
from httpx import AsyncClient

from tests.factories import (
    make_income,
    make_membership,
    make_organization,
    make_project,
    make_project_member,
    make_user,
)
from tests.helpers import LoggedInActor, login_as_existing
from trinol.core.authz.permissions import Role
from trinol.modules.ai.models import EMBEDDING_DIMENSIONS
from trinol.modules.identity.models import Membership, Organization, User

# Phase 8 Stage 4 — the load-bearing test of the whole phase: proves the
# retrieval-filter mechanism (ADR-0014) actually stops a MEMBER's search
# and the assistant's answer from surfacing a project they aren't a
# member of, or any finance figure at all.

pytestmark = pytest.mark.usefixtures("db_session")


@dataclass(frozen=True, slots=True)
class _Fixture:
    organization: Organization
    owner_user: User
    owner_membership: Membership
    member_user: User
    member_membership: Membership


async def _setup_two_projects_and_finance(db_session) -> _Fixture:
    """One project the MEMBER belongs to, one they don't (MANAGER+-only
    visible); some finance data so an ADMIN's assistant answer has a real
    figure to (not) leak. Pure DB setup — no HTTP login here, so each
    test logs in as whichever actor it actually needs, on its own."""
    organization = await make_organization(db_session)
    owner_user = await make_user(db_session, email=f"assistant-owner-{organization.id}@x.com")
    owner_membership = await make_membership(
        db_session, organization=organization, user=owner_user, role=Role.OWNER
    )
    member_user = await make_user(db_session, email=f"assistant-member-{organization.id}@x.com")
    member_membership = await make_membership(
        db_session, organization=organization, user=member_user, role=Role.MEMBER
    )

    member_project = await make_project(
        db_session, organization=organization, owner=owner_membership, name="Member Visible Project"
    )
    await make_project_member(db_session, project=member_project, user=member_user)

    await make_project(
        db_session, organization=organization, owner=owner_membership, name="Manager Only Project"
    )
    # No project_members row for member_user on the second project — a
    # plain MEMBER should never see it, per ensure_project_visible.

    await make_income(
        db_session,
        organization=organization,
        created_by=owner_membership,
        amount=Decimal("5000.00"),
        source="Retainer",
    )
    await db_session.commit()

    return _Fixture(
        organization=organization,
        owner_user=owner_user,
        owner_membership=owner_membership,
        member_user=member_user,
        member_membership=member_membership,
    )


async def _login_as_member(client: AsyncClient, fake_verifier, fixture: _Fixture) -> LoggedInActor:
    return await login_as_existing(
        client,
        fake_verifier,
        user=fixture.member_user,
        membership=fixture.member_membership,
        organization=fixture.organization,
    )


async def _login_as_owner(client: AsyncClient, fake_verifier, fixture: _Fixture) -> LoggedInActor:
    return await login_as_existing(
        client,
        fake_verifier,
        user=fixture.owner_user,
        membership=fixture.owner_membership,
        organization=fixture.organization,
    )


async def test_member_search_never_returns_a_project_they_are_not_a_member_of(
    client: AsyncClient, fake_verifier, fake_ai_client, db_session
) -> None:
    fixture = await _setup_two_projects_and_finance(db_session)
    await _login_as_member(client, fake_verifier, fixture)
    # Force every embedding (index-time and query-time) to the identical
    # vector, so both projects tie for "closest match" — the only thing
    # that can exclude the MANAGER-only one is the permission filter, not
    # incidental low similarity ranking.
    fake_ai_client.next_embedding = [0.1] * EMBEDDING_DIMENSIONS

    response = await client.get("/api/v1/ai/search?q=project+status")
    assert response.status_code == 200
    contents = " ".join(item["content"] for item in response.json()["items"])
    assert "Member Visible Project" in contents
    assert "Manager Only Project" not in contents


async def test_manager_search_sees_both_projects(
    client: AsyncClient, fake_verifier, fake_ai_client, db_session
) -> None:
    fixture = await _setup_two_projects_and_finance(db_session)
    await _login_as_owner(client, fake_verifier, fixture)
    fake_ai_client.next_embedding = [0.1] * EMBEDDING_DIMENSIONS

    response = await client.get("/api/v1/ai/search?q=project+status")
    assert response.status_code == 200
    contents = " ".join(item["content"] for item in response.json()["items"])
    assert "Member Visible Project" in contents
    assert "Manager Only Project" in contents


async def test_member_assistant_context_never_contains_financial_data(
    client: AsyncClient, fake_verifier, fake_ai_client, db_session
) -> None:
    fixture = await _setup_two_projects_and_finance(db_session)
    member = await _login_as_member(client, fake_verifier, fixture)
    fake_ai_client.next_embedding = [0.1] * EMBEDDING_DIMENSIONS

    response = await client.post(
        "/api/v1/ai/assistant/ask",
        json={"question": "How much revenue did we make this month?"},
        headers={"X-CSRF-Token": member.csrf_token},
    )
    assert response.status_code == 200
    prompt = fake_ai_client.calls[-1][1]
    assert "VERIFIED FINANCIAL DATA" not in prompt
    assert "5000.00" not in prompt


async def test_owner_assistant_context_contains_the_real_financial_data(
    client: AsyncClient, fake_verifier, fake_ai_client, db_session
) -> None:
    fixture = await _setup_two_projects_and_finance(db_session)
    owner = await _login_as_owner(client, fake_verifier, fixture)
    fake_ai_client.next_embedding = [0.1] * EMBEDDING_DIMENSIONS

    response = await client.post(
        "/api/v1/ai/assistant/ask",
        json={"question": "How much revenue did we make this month?"},
        headers={"X-CSRF-Token": owner.csrf_token},
    )
    assert response.status_code == 200
    prompt = fake_ai_client.calls[-1][1]
    assert "VERIFIED FINANCIAL DATA" in prompt
    assert "5000.00" in prompt


async def test_assistant_use_requires_org_membership_but_no_special_permission(
    client: AsyncClient, fake_verifier, fake_ai_client, db_session
) -> None:
    """AI_ASSISTANT_USE is MEMBER-tier (RBAC.md §2) — every role reaches
    the route; the restriction lives entirely in the retrieval filter,
    not a 403 here."""
    fixture = await _setup_two_projects_and_finance(db_session)
    member = await _login_as_member(client, fake_verifier, fixture)
    response = await client.post(
        "/api/v1/ai/assistant/ask",
        json={"question": "Anything interesting?"},
        headers={"X-CSRF-Token": member.csrf_token},
    )
    assert response.status_code == 200

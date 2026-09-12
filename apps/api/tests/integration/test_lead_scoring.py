from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.factories import make_lead, make_membership, make_user
from tests.helpers import login_as, login_as_existing
from trinol.core.authz.permissions import Role

# Reuses LEAD_READ/LEAD_WRITE's existing tiers — leads have no
# ownership-split (RBAC.md), so no service-level restriction beyond the
# route's own require(...). Every test here uses fake_ai_client (never
# the real provider) — see test_authz_matrix.py's _AI_PROVIDER_ROUTES for
# why this route can't be covered by the generic matrix test instead.

pytestmark = pytest.mark.usefixtures("db_session")


async def test_manager_can_score_a_lead(
    client: AsyncClient, fake_verifier, fake_ai_client, db_session
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.MANAGER)
    lead = await make_lead(db_session, organization=actor.organization, name="Acme Co")
    await db_session.commit()
    fake_ai_client.next_response = "82\nStrong fit: high estimated value and an active stage."

    response = await client.post(
        f"/api/v1/leads/{lead.id}/score", headers={"X-CSRF-Token": actor.csrf_token}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["score"] == 82
    assert "Strong fit" in body["rationale"]
    assert body["stale"] is False
    assert body["computed_by"] == str(actor.membership.user_id)


async def test_member_cannot_score_a_lead(
    client: AsyncClient, fake_verifier, fake_ai_client, db_session
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.MEMBER)
    lead = await make_lead(db_session, organization=actor.organization)
    await db_session.commit()

    response = await client.post(
        f"/api/v1/leads/{lead.id}/score", headers={"X-CSRF-Token": actor.csrf_token}
    )
    assert response.status_code == 403
    assert fake_ai_client.calls == []


async def test_member_can_view_a_score_a_manager_computed(
    client: AsyncClient, fake_verifier, fake_ai_client, db_session
) -> None:
    manager = await login_as(client, fake_verifier, db_session, role=Role.MANAGER)
    lead = await make_lead(db_session, organization=manager.organization)
    await db_session.commit()
    fake_ai_client.next_response = "70\nGood fit."
    await client.post(
        f"/api/v1/leads/{lead.id}/score", headers={"X-CSRF-Token": manager.csrf_token}
    )

    member_user = await make_user(db_session, email=f"score-viewer-{manager.organization.id}@x.com")
    member_membership = await make_membership(
        db_session, organization=manager.organization, user=member_user, role=Role.MEMBER
    )
    await db_session.commit()
    await login_as_existing(
        client,
        fake_verifier,
        user=member_user,
        membership=member_membership,
        organization=manager.organization,
    )

    response = await client.get(f"/api/v1/leads/{lead.id}/score")
    assert response.status_code == 200
    assert response.json()["score"] == 70


async def test_get_score_before_scoring_is_404(
    client: AsyncClient, fake_verifier, fake_ai_client, db_session
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.MEMBER)
    lead = await make_lead(db_session, organization=actor.organization)
    await db_session.commit()

    response = await client.get(f"/api/v1/leads/{lead.id}/score")
    assert response.status_code == 404


async def test_score_is_clamped_to_0_100(
    client: AsyncClient, fake_verifier, fake_ai_client, db_session
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.MANAGER)
    lead = await make_lead(db_session, organization=actor.organization)
    await db_session.commit()
    fake_ai_client.next_response = "150\nOver-eager model output."

    response = await client.post(
        f"/api/v1/leads/{lead.id}/score", headers={"X-CSRF-Token": actor.csrf_token}
    )
    assert response.status_code == 200
    assert response.json()["score"] == 100


async def test_negative_score_is_clamped_to_0(
    client: AsyncClient, fake_verifier, fake_ai_client, db_session
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.MANAGER)
    lead = await make_lead(db_session, organization=actor.organization)
    await db_session.commit()
    fake_ai_client.next_response = "-20\nNegative fit, should still clamp."

    response = await client.post(
        f"/api/v1/leads/{lead.id}/score", headers={"X-CSRF-Token": actor.csrf_token}
    )
    assert response.status_code == 200
    assert response.json()["score"] == 0


async def test_rescoring_replaces_the_score_without_duplicating(
    client: AsyncClient, fake_verifier, fake_ai_client, db_session
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.MANAGER)
    lead = await make_lead(db_session, organization=actor.organization)
    await db_session.commit()

    fake_ai_client.next_response = "30\nFirst pass."
    first = await client.post(
        f"/api/v1/leads/{lead.id}/score", headers={"X-CSRF-Token": actor.csrf_token}
    )
    fake_ai_client.next_response = "90\nSecond pass, much stronger signal."
    second = await client.post(
        f"/api/v1/leads/{lead.id}/score", headers={"X-CSRF-Token": actor.csrf_token}
    )

    assert first.json()["id"] == second.json()["id"]
    assert second.json()["score"] == 90

    get_response = await client.get(f"/api/v1/leads/{lead.id}/score")
    assert get_response.json()["score"] == 90


async def test_score_for_another_org_lead_is_404(
    client: AsyncClient, fake_verifier, fake_ai_client, db_session
) -> None:
    other_actor = await login_as(client, fake_verifier, db_session, role=Role.MANAGER)
    other_lead = await make_lead(db_session, organization=other_actor.organization)
    await db_session.commit()

    actor = await login_as(client, fake_verifier, db_session, role=Role.ADMIN)
    get_response = await client.get(f"/api/v1/leads/{other_lead.id}/score")
    assert get_response.status_code == 404
    post_response = await client.post(
        f"/api/v1/leads/{other_lead.id}/score", headers={"X-CSRF-Token": actor.csrf_token}
    )
    assert post_response.status_code == 404
    assert fake_ai_client.calls == []

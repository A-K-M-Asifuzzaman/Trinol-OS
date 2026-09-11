from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
from httpx import AsyncClient

from tests.factories import make_lead, make_membership, make_organization, make_user
from tests.helpers import login_as
from trinol.core.authz.permissions import Role
from trinol.modules.crm.models import LeadStage

pytestmark = pytest.mark.usefixtures("db_session")


async def test_pipeline_value_sums_open_stage_leads_only(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.MANAGER)
    await make_lead(
        db_session,
        organization=actor.organization,
        email="open1@x.com",
        stage=LeadStage.NEW,
        estimated_value=Decimal("1000"),
    )
    await make_lead(
        db_session,
        organization=actor.organization,
        email="open2@x.com",
        stage=LeadStage.NEGOTIATION,
        estimated_value=Decimal("2500.50"),
    )
    # Excluded: closed stages, even with a real estimated_value.
    await make_lead(
        db_session,
        organization=actor.organization,
        email="won@x.com",
        stage=LeadStage.WON,
        estimated_value=Decimal("9999"),
    )
    await make_lead(
        db_session,
        organization=actor.organization,
        email="lost@x.com",
        stage=LeadStage.LOST,
        estimated_value=Decimal("9999"),
    )
    # Excluded: no estimated_value at all.
    await make_lead(db_session, organization=actor.organization, email="noval@x.com")
    await db_session.commit()

    response = await client.get("/api/v1/leads/stats")
    assert response.status_code == 200
    assert response.json()["pipeline_value"] == "3500.50"


async def test_pipeline_value_is_null_with_no_open_estimated_values(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.MANAGER)
    await make_lead(db_session, organization=actor.organization, email="noval@x.com")
    await db_session.commit()

    response = await client.get("/api/v1/leads/stats")
    assert response.status_code == 200
    assert response.json()["pipeline_value"] is None


async def test_follow_ups_due_counts_today_and_earlier_not_future(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.MANAGER)
    today = date.today()
    await make_lead(
        db_session,
        organization=actor.organization,
        email="overdue@x.com",
        next_follow_up=today - timedelta(days=1),
    )
    await make_lead(
        db_session, organization=actor.organization, email="today@x.com", next_follow_up=today
    )
    await make_lead(
        db_session,
        organization=actor.organization,
        email="future@x.com",
        next_follow_up=today + timedelta(days=1),
    )
    await make_lead(db_session, organization=actor.organization, email="none@x.com")
    await db_session.commit()

    response = await client.get("/api/v1/leads/stats")
    assert response.status_code == 200
    assert response.json()["follow_ups_due"] == 2


async def test_conversion_rate_computed_from_won_and_lost_leads(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    """Phase 7 plan decision 4: won / (won + lost), all-time, ignoring
    still-open leads entirely."""
    actor = await login_as(client, fake_verifier, db_session, role=Role.MANAGER)
    await make_lead(
        db_session, organization=actor.organization, email="won1@x.com", stage=LeadStage.WON
    )
    await make_lead(
        db_session, organization=actor.organization, email="won2@x.com", stage=LeadStage.WON
    )
    await make_lead(
        db_session, organization=actor.organization, email="lost1@x.com", stage=LeadStage.LOST
    )
    await make_lead(
        db_session, organization=actor.organization, email="open1@x.com", stage=LeadStage.NEW
    )
    await db_session.commit()

    response = await client.get("/api/v1/leads/stats")
    assert response.status_code == 200
    assert response.json()["conversion_rate"] == pytest.approx(2 / 3)


async def test_conversion_rate_is_null_with_no_decided_leads(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.MANAGER)
    await make_lead(
        db_session, organization=actor.organization, email="open1@x.com", stage=LeadStage.NEW
    )
    await db_session.commit()

    response = await client.get("/api/v1/leads/stats")
    assert response.status_code == 200
    assert response.json()["conversion_rate"] is None


async def test_stats_is_org_scoped(client: AsyncClient, fake_verifier, db_session) -> None:
    other_org = await make_organization(db_session)
    other_owner = await make_user(db_session, email=f"owner-{other_org.id}@x.com")
    other_actor = await make_membership(
        db_session, organization=other_org, user=other_owner, role=Role.MANAGER
    )
    await make_lead(
        db_session,
        organization=other_org,
        assigned_to=other_actor,
        email="other@x.com",
        estimated_value=Decimal("5000"),
        next_follow_up=date.today(),
    )
    await db_session.commit()

    await login_as(client, fake_verifier, db_session, role=Role.MANAGER)
    response = await client.get("/api/v1/leads/stats")
    assert response.status_code == 200
    body = response.json()
    assert body["pipeline_value"] is None
    assert body["follow_ups_due"] == 0
    assert body["conversion_rate"] is None

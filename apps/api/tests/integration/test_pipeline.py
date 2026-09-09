from __future__ import annotations

from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from tests.factories import make_lead
from tests.helpers import login_as
from trinol.core.authz.permissions import Role
from trinol.modules.crm.models import LeadStage, LeadStageEvent

pytestmark = pytest.mark.usefixtures("db_session")


async def test_pipeline_groups_leads_by_stage(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.OWNER)
    await make_lead(db_session, organization=actor.organization, name="New Lead", email="new@x.com")
    await make_lead(
        db_session,
        organization=actor.organization,
        name="Won Lead",
        email="won@x.com",
        stage=LeadStage.WON,
    )
    await db_session.commit()

    response = await client.get("/api/v1/pipeline")
    assert response.status_code == 200
    body = response.json()
    columns_by_stage = {column["stage"]: column["leads"] for column in body["columns"]}
    assert [lead["name"] for lead in columns_by_stage["NEW"]] == ["New Lead"]
    assert [lead["name"] for lead in columns_by_stage["WON"]] == ["Won Lead"]
    assert columns_by_stage["LOST"] == []
    assert body["total"] == 2
    assert body["truncated"] is False


async def test_pipeline_orders_within_a_column_by_board_position(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.OWNER)
    await make_lead(
        db_session,
        organization=actor.organization,
        name="Second",
        email="second@x.com",
        board_position=Decimal("2"),
    )
    await make_lead(
        db_session,
        organization=actor.organization,
        name="First",
        email="first@x.com",
        board_position=Decimal("1"),
    )
    await db_session.commit()

    response = await client.get("/api/v1/pipeline")
    new_leads = next(c for c in response.json()["columns"] if c["stage"] == "NEW")["leads"]
    assert [lead["name"] for lead in new_leads] == ["First", "Second"]


async def test_pipeline_caps_at_500_leads_and_reports_truncation(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.OWNER)
    for i in range(501):
        await make_lead(
            db_session,
            organization=actor.organization,
            name=f"Lead {i}",
            email=f"lead{i}@x.com",
            board_position=Decimal(i),
        )
    await db_session.commit()

    response = await client.get("/api/v1/pipeline")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 501
    assert body["truncated"] is True
    returned_count = sum(len(column["leads"]) for column in body["columns"])
    assert returned_count == 500


@pytest.mark.parametrize("role", [Role.MEMBER, Role.MANAGER, Role.ADMIN, Role.OWNER])
async def test_every_role_can_view_the_pipeline(
    client: AsyncClient, fake_verifier, db_session, role: Role
) -> None:
    await login_as(client, fake_verifier, db_session, role=role)
    response = await client.get("/api/v1/pipeline")
    assert response.status_code == 200


async def test_drag_across_columns_via_patch_writes_one_stage_event(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    """Decision 1 (Phase 2 precedent, applied identically): no dedicated
    reorder endpoint — the client computes the midpoint and PATCHes both
    board_position and stage as ordinary lead fields in one request."""
    actor = await login_as(client, fake_verifier, db_session, role=Role.OWNER)
    lead = await make_lead(
        db_session,
        organization=actor.organization,
        email="drag@x.com",
        board_position=Decimal("1"),
    )
    await db_session.commit()

    response = await client.patch(
        f"/api/v1/leads/{lead.id}",
        json={"stage": "CONTACTED", "board_position": "5"},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["stage"] == "CONTACTED"
    assert body["board_position"] == "5"

    events_result = await db_session.execute(
        select(LeadStageEvent).where(
            LeadStageEvent.organization_id == actor.organization.id,
            LeadStageEvent.lead_id == lead.id,
        )
    )
    events = events_result.scalars().all()
    assert len(events) == 1
    assert events[0].from_stage == "NEW"
    assert events[0].to_stage == "CONTACTED"


async def test_reorder_within_a_column_writes_no_stage_event(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.OWNER)
    lead = await make_lead(
        db_session,
        organization=actor.organization,
        email="reorder@x.com",
        board_position=Decimal("1"),
    )
    await db_session.commit()

    response = await client.patch(
        f"/api/v1/leads/{lead.id}",
        json={"board_position": "5"},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == 200
    assert response.json()["board_position"] == "5"
    assert response.json()["stage"] == "NEW"

    events_result = await db_session.execute(
        select(LeadStageEvent).where(
            LeadStageEvent.organization_id == actor.organization.id,
            LeadStageEvent.lead_id == lead.id,
        )
    )
    assert events_result.scalars().all() == []

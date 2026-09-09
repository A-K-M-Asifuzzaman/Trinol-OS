from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from tests.factories import make_membership, make_organization, make_user
from tests.helpers import login_as
from trinol.core.authz.permissions import Role
from trinol.modules.crm.models import LeadStage, LeadStageEvent
from trinol.modules.crm.services.lead_service import create_lead

pytestmark = pytest.mark.usefixtures("db_session")


@pytest.mark.parametrize("role", [Role.MANAGER, Role.ADMIN, Role.OWNER])
async def test_manager_and_up_can_create_lead(
    client: AsyncClient, fake_verifier, db_session, role: Role
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=role)
    response = await client.post(
        "/api/v1/leads",
        json={"name": "Jane Prospect", "email": "jane@prospect.test", "source": "WEBSITE"},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Jane Prospect"
    assert body["source"] == "WEBSITE"
    assert body["stage"] == "NEW"
    assert body["currency"] == "USD"
    assert body["archived_at"] is None
    assert body["converted_client_id"] is None


async def test_member_cannot_create_lead(client: AsyncClient, fake_verifier, db_session) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.MEMBER)
    response = await client.post(
        "/api/v1/leads",
        json={"name": "Jane Prospect", "email": "jane@prospect.test", "source": "WEBSITE"},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == 403


async def test_create_lead_requires_email_or_phone(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.OWNER)
    response = await client.post(
        "/api/v1/leads",
        json={"name": "Jane Prospect", "source": "WEBSITE"},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == 422


async def test_create_lead_with_only_phone_is_valid(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.OWNER)
    response = await client.post(
        "/api/v1/leads",
        json={"name": "Jane Prospect", "phone": "+1-555-0100", "source": "PHONE"},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == 201


async def test_create_lead_rejects_assigned_to_not_in_organization(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.ADMIN)
    other_org = await make_organization(db_session)
    outsider = await make_user(db_session, email=f"outsider-{other_org.id}@x.com")
    await make_membership(db_session, organization=other_org, user=outsider, role=Role.MEMBER)
    await db_session.commit()

    response = await client.post(
        "/api/v1/leads",
        json={
            "name": "Jane Prospect",
            "email": "jane@prospect.test",
            "source": "WEBSITE",
            "assigned_to": str(outsider.id),
        },
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == 400


@pytest.mark.parametrize("role", [Role.MEMBER, Role.MANAGER, Role.ADMIN, Role.OWNER])
async def test_every_role_can_list_and_get_leads(
    client: AsyncClient, fake_verifier, db_session, role: Role
) -> None:
    """RBAC.md §2: "Leads & clients: view" is open to every role."""
    actor = await login_as(client, fake_verifier, db_session, role=role)
    owner = await make_user(db_session, email=f"lead-owner-{actor.organization.id}@x.com")
    owner_membership = await make_membership(
        db_session, organization=actor.organization, user=owner, role=Role.OWNER
    )
    await db_session.commit()
    seeded = await create_lead(
        db_session,
        organization_id=actor.organization.id,
        actor=owner_membership,
        name="Jane Prospect",
        company=None,
        email="jane@prospect.test",
        phone=None,
        source="WEBSITE",
        service=None,
        estimated_value=None,
        currency="USD",
        stage=LeadStage.NEW,
        assigned_to=None,
        next_follow_up=None,
        notes=None,
    )

    list_response = await client.get("/api/v1/leads")
    assert list_response.status_code == 200
    assert any(item["id"] == str(seeded.id) for item in list_response.json()["items"])

    get_response = await client.get(f"/api/v1/leads/{seeded.id}")
    assert get_response.status_code == 200
    assert get_response.json()["name"] == "Jane Prospect"


async def test_list_leads_filters_by_stage(client: AsyncClient, fake_verifier, db_session) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.OWNER)
    new_lead = (
        await client.post(
            "/api/v1/leads",
            json={"name": "New Lead", "email": "new@prospect.test", "source": "WEBSITE"},
            headers={"X-CSRF-Token": actor.csrf_token},
        )
    ).json()
    contacted_lead = (
        await client.post(
            "/api/v1/leads",
            json={"name": "Contacted Lead", "email": "contacted@prospect.test", "source": "EMAIL"},
            headers={"X-CSRF-Token": actor.csrf_token},
        )
    ).json()
    patch_response = await client.patch(
        f"/api/v1/leads/{contacted_lead['id']}",
        json={"stage": "CONTACTED"},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert patch_response.status_code == 200

    response = await client.get("/api/v1/leads", params={"stage": "CONTACTED"})
    assert response.status_code == 200
    ids = [item["id"] for item in response.json()["items"]]
    assert contacted_lead["id"] in ids
    assert new_lead["id"] not in ids


@pytest.mark.parametrize(
    ("from_stage", "to_stage"),
    [
        ("NEW", "CONTACTED"),
        ("CONTACTED", "MEETING"),
        ("MEETING", "PROPOSAL"),
        ("PROPOSAL", "NEGOTIATION"),
        ("NEGOTIATION", "WON"),
        ("NEW", "LOST"),
        ("NEGOTIATION", "LOST"),
    ],
)
async def test_stage_transition_writes_exactly_one_stage_event(
    client: AsyncClient, fake_verifier, db_session, from_stage: str, to_stage: str
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.OWNER)
    create_response = await client.post(
        "/api/v1/leads",
        json={
            "name": "Jane Prospect",
            "email": "jane@prospect.test",
            "source": "WEBSITE",
            "stage": from_stage,
        },
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    lead_id = create_response.json()["id"]

    response = await client.patch(
        f"/api/v1/leads/{lead_id}",
        json={"stage": to_stage},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == 200
    assert response.json()["stage"] == to_stage

    events_result = await db_session.execute(
        select(LeadStageEvent).where(
            LeadStageEvent.organization_id == actor.organization.id,
            LeadStageEvent.lead_id == lead_id,
        )
    )
    events = events_result.scalars().all()
    assert len(events) == 1
    assert events[0].from_stage == from_stage
    assert events[0].to_stage == to_stage
    assert events[0].actor_id == actor.membership.user_id


async def test_updating_unrelated_field_writes_no_stage_event(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.OWNER)
    create_response = await client.post(
        "/api/v1/leads",
        json={"name": "Jane Prospect", "email": "jane@prospect.test", "source": "WEBSITE"},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    lead_id = create_response.json()["id"]

    response = await client.patch(
        f"/api/v1/leads/{lead_id}",
        json={"notes": "Called, left voicemail"},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == 200

    events_result = await db_session.execute(
        select(LeadStageEvent).where(
            LeadStageEvent.organization_id == actor.organization.id,
            LeadStageEvent.lead_id == lead_id,
        )
    )
    assert events_result.scalars().all() == []


async def test_setting_stage_to_same_value_writes_no_stage_event(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.OWNER)
    create_response = await client.post(
        "/api/v1/leads",
        json={"name": "Jane Prospect", "email": "jane@prospect.test", "source": "WEBSITE"},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    lead_id = create_response.json()["id"]

    response = await client.patch(
        f"/api/v1/leads/{lead_id}",
        json={"stage": "NEW"},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == 200

    events_result = await db_session.execute(
        select(LeadStageEvent).where(
            LeadStageEvent.organization_id == actor.organization.id,
            LeadStageEvent.lead_id == lead_id,
        )
    )
    assert events_result.scalars().all() == []


async def test_patch_can_set_lost_reason(client: AsyncClient, fake_verifier, db_session) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.OWNER)
    create_response = await client.post(
        "/api/v1/leads",
        json={"name": "Jane Prospect", "email": "jane@prospect.test", "source": "WEBSITE"},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    lead_id = create_response.json()["id"]

    response = await client.patch(
        f"/api/v1/leads/{lead_id}",
        json={"stage": "LOST", "lost_reason": "Went with a competitor"},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["stage"] == "LOST"
    assert body["lost_reason"] == "Went with a competitor"


async def test_patch_rejects_nulling_both_email_and_phone(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.OWNER)
    create_response = await client.post(
        "/api/v1/leads",
        json={"name": "Jane Prospect", "email": "jane@prospect.test", "source": "WEBSITE"},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    lead_id = create_response.json()["id"]

    response = await client.patch(
        f"/api/v1/leads/{lead_id}",
        json={"email": None, "phone": None},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == 422


async def test_list_leads_excludes_archived(client: AsyncClient, fake_verifier, db_session) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.OWNER)
    create_response = await client.post(
        "/api/v1/leads",
        json={"name": "Jane Prospect", "email": "jane@prospect.test", "source": "WEBSITE"},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    lead_id = create_response.json()["id"]

    delete_response = await client.delete(
        f"/api/v1/leads/{lead_id}", headers={"X-CSRF-Token": actor.csrf_token}
    )
    assert delete_response.status_code == 200
    assert delete_response.json()["archived_at"] is not None

    list_response = await client.get("/api/v1/leads")
    assert list_response.status_code == 200
    assert all(item["id"] != lead_id for item in list_response.json()["items"])


async def test_lead_in_another_org_is_404(client: AsyncClient, fake_verifier, db_session) -> None:
    other_org = await make_organization(db_session)
    other_owner = await make_user(db_session, email=f"owner-{other_org.id}@x.com")
    other_actor = await make_membership(
        db_session, organization=other_org, user=other_owner, role=Role.OWNER
    )
    await db_session.commit()

    other_lead = await create_lead(
        db_session,
        organization_id=other_org.id,
        actor=other_actor,
        name="Other Org Lead",
        company=None,
        email="other@prospect.test",
        phone=None,
        source="WEBSITE",
        service=None,
        estimated_value=None,
        currency="USD",
        stage=LeadStage.NEW,
        assigned_to=None,
        next_follow_up=None,
        notes=None,
    )

    actor = await login_as(client, fake_verifier, db_session, role=Role.ADMIN)

    get_response = await client.get(f"/api/v1/leads/{other_lead.id}")
    assert get_response.status_code == 404

    patch_response = await client.patch(
        f"/api/v1/leads/{other_lead.id}",
        json={"notes": "hijack"},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert patch_response.status_code == 404

    delete_response = await client.delete(
        f"/api/v1/leads/{other_lead.id}", headers={"X-CSRF-Token": actor.csrf_token}
    )
    assert delete_response.status_code == 404

from __future__ import annotations

import asyncio

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from tests.factories import make_lead, make_membership, make_organization, make_user
from tests.helpers import login_as
from trinol.core.authz.permissions import Role
from trinol.core.db.engine import get_session_factory
from trinol.core.errors import ConflictError
from trinol.modules.crm.models import Client, Lead, LeadStage, LeadStageEvent
from trinol.modules.identity.models import Membership
from trinol.modules.work.models import Project, ProjectMember
from trinol.modules.work.services.lead_conversion_service import convert_lead
from trinol.platform.models import ActivityEvent

pytestmark = pytest.mark.usefixtures("db_session")


async def test_convert_lead_creates_client_and_project_in_one_transaction(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.MANAGER)
    lead = await make_lead(
        db_session,
        organization=actor.organization,
        name="Acme Corp Lead",
        email="acme@x.com",
        stage=LeadStage.NEGOTIATION,
    )
    await db_session.commit()

    response = await client.post(
        f"/api/v1/leads/{lead.id}/convert", headers={"X-CSRF-Token": actor.csrf_token}
    )
    assert response.status_code == 200
    body = response.json()
    client_id = body["client"]["id"]
    assert body["project"]["client_id"] == client_id
    assert body["lead"]["converted_client_id"] == client_id
    assert body["lead"]["stage"] == "WON"

    clients_result = await db_session.execute(
        select(Client).where(Client.organization_id == actor.organization.id)
    )
    assert len(clients_result.scalars().all()) == 1

    projects_result = await db_session.execute(
        select(Project).where(Project.organization_id == actor.organization.id)
    )
    projects = projects_result.scalars().all()
    assert len(projects) == 1
    assert str(projects[0].client_id) == client_id

    members_result = await db_session.execute(
        select(ProjectMember).where(
            ProjectMember.organization_id == actor.organization.id,
            ProjectMember.project_id == projects[0].id,
        )
    )
    assert len(members_result.scalars().all()) == 1

    lead_result = await db_session.execute(
        select(Lead).where(Lead.organization_id == actor.organization.id, Lead.id == lead.id)
    )
    refreshed_lead = lead_result.scalar_one()
    assert refreshed_lead.converted_at is not None
    assert str(refreshed_lead.converted_client_id) == client_id

    events_result = await db_session.execute(
        select(LeadStageEvent).where(
            LeadStageEvent.organization_id == actor.organization.id,
            LeadStageEvent.lead_id == lead.id,
        )
    )
    events = events_result.scalars().all()
    assert len(events) == 1
    assert events[0].from_stage == "NEGOTIATION"
    assert events[0].to_stage == "WON"

    activity_result = await db_session.execute(
        select(ActivityEvent).where(ActivityEvent.organization_id == actor.organization.id)
    )
    activity_by_event = {row.event: row for row in activity_result.scalars().all()}
    assert activity_by_event["client.created"].is_audit is False
    assert activity_by_event["project.created"].is_audit is False
    assert activity_by_event["lead.converted"].is_audit is True


async def test_member_cannot_convert_lead(client: AsyncClient, fake_verifier, db_session) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.MEMBER)
    lead = await make_lead(db_session, organization=actor.organization, email="member@x.com")
    await db_session.commit()

    response = await client.post(
        f"/api/v1/leads/{lead.id}/convert", headers={"X-CSRF-Token": actor.csrf_token}
    )
    assert response.status_code == 403


async def test_converting_an_already_converted_lead_conflicts(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.MANAGER)
    lead = await make_lead(db_session, organization=actor.organization, email="twice@x.com")
    await db_session.commit()

    first = await client.post(
        f"/api/v1/leads/{lead.id}/convert", headers={"X-CSRF-Token": actor.csrf_token}
    )
    assert first.status_code == 200

    second = await client.post(
        f"/api/v1/leads/{lead.id}/convert", headers={"X-CSRF-Token": actor.csrf_token}
    )
    assert second.status_code == 409


async def test_converting_an_archived_lead_conflicts(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.MANAGER)
    lead = await make_lead(db_session, organization=actor.organization, email="archived@x.com")
    await db_session.commit()

    archive_response = await client.delete(
        f"/api/v1/leads/{lead.id}", headers={"X-CSRF-Token": actor.csrf_token}
    )
    assert archive_response.status_code == 200

    response = await client.post(
        f"/api/v1/leads/{lead.id}/convert", headers={"X-CSRF-Token": actor.csrf_token}
    )
    assert response.status_code == 409


async def test_concurrent_conversion_of_the_same_lead_only_one_succeeds() -> None:
    """Codex P1: convert_lead's archived/already-converted check raced a
    concurrent call with no lock — two simultaneous conversions of the
    same lead could both pass it and each create their own Client+Project.
    Needs two genuinely independent DB connections, not two SAVEPOINTs
    sharing one transaction — the point is Postgres actually serializing
    the two via the lead row's own FOR UPDATE lock (lead_service.
    get_lead_in_org's for_update=True), same approach and reason as
    test_invitations.py's duplicate-invitation race test. Real commits,
    no test fixtures — this needs sessions outside the fixture's rollback
    boundary."""
    session_factory = get_session_factory()

    setup_session = session_factory()
    try:
        org = await make_organization(setup_session)
        manager_user = await make_user(setup_session, email=f"manager-{org.id}@x.com")
        manager = await make_membership(
            setup_session, organization=org, user=manager_user, role=Role.MANAGER
        )
        lead = await make_lead(setup_session, organization=org, email=f"race-{org.id}@x.com")
        await setup_session.commit()
        org_id, manager_id, lead_id = org.id, manager.id, lead.id
    finally:
        await setup_session.close()

    session_1 = session_factory()
    session_2 = session_factory()
    try:
        actor_1 = (
            await session_1.execute(
                select(Membership).where(
                    Membership.organization_id == org_id, Membership.id == manager_id
                )
            )
        ).scalar_one()
        actor_2 = (
            await session_2.execute(
                select(Membership).where(
                    Membership.organization_id == org_id, Membership.id == manager_id
                )
            )
        ).scalar_one()

        results = await asyncio.gather(
            convert_lead(session_1, organization_id=org_id, actor=actor_1, lead_id=lead_id),
            convert_lead(session_2, organization_id=org_id, actor=actor_2, lead_id=lead_id),
            return_exceptions=True,
        )

        successes = [r for r in results if not isinstance(r, Exception)]
        failures = [r for r in results if isinstance(r, Exception)]
        assert len(successes) == 1, f"expected exactly one success, got: {results}"
        assert len(failures) == 1
        assert isinstance(failures[0], ConflictError)

        clients_remaining = (
            (await session_1.execute(select(Client).where(Client.organization_id == org_id)))
            .scalars()
            .all()
        )
        assert len(clients_remaining) == 1, "the race must never produce two clients"

        projects_remaining = (
            (await session_1.execute(select(Project).where(Project.organization_id == org_id)))
            .scalars()
            .all()
        )
        assert len(projects_remaining) == 1, "the race must never produce two projects"
    finally:
        await session_1.close()
        await session_2.close()


async def test_converting_a_lead_in_another_org_is_404(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    other_org = await make_organization(db_session)
    other_owner = await make_user(db_session, email=f"owner-{other_org.id}@x.com")
    other_actor = await make_membership(
        db_session, organization=other_org, user=other_owner, role=Role.MANAGER
    )
    other_lead = await make_lead(
        db_session, organization=other_org, assigned_to=other_actor, email="other@x.com"
    )
    await db_session.commit()

    actor = await login_as(client, fake_verifier, db_session, role=Role.MANAGER)
    response = await client.post(
        f"/api/v1/leads/{other_lead.id}/convert", headers={"X-CSRF-Token": actor.csrf_token}
    )
    assert response.status_code == 404

from __future__ import annotations

from datetime import date, timedelta

import pytest
from httpx import AsyncClient

from tests.factories import make_membership, make_organization, make_project, make_task, make_user
from tests.helpers import login_as
from trinol.core.authz.permissions import Role

# Reuses project_service's own visibility rule for the single-project
# route (real ownership-split, RBAC.md §3 "Project detail") and
# work.services.analytics_service.get_project_analytics's own MEMBER-
# sees-own/MANAGER+-sees-all filter for the org-wide list. Every test
# that hits the single-project route uses fake_ai_client (never the real
# provider) — see test_authz_matrix.py's _AI_PROVIDER_ROUTES.

pytestmark = pytest.mark.usefixtures("db_session")


async def _add_overdue_task(db_session, *, organization, created_by, project) -> None:
    await make_task(
        db_session,
        organization=organization,
        created_by=created_by,
        project=project,
        due_date=date.today() - timedelta(days=1),
    )


async def test_level_crosses_thresholds_purely_from_overdue_count_never_touching_the_ai_client(
    client: AsyncClient, fake_verifier, fake_ai_client, db_session
) -> None:
    """Codex-adjacent proof required by the Stage 6 plan: the level must
    never depend on the LLM. GET /ai/project-risk never calls ai_client
    at all (list_project_risk's own design), so this is checked via that
    route — the fake client's call count staying at zero across both
    assertions is itself part of the proof, not incidental."""
    actor = await login_as(client, fake_verifier, db_session, role=Role.MEMBER)
    project = await make_project(
        db_session, organization=actor.organization, owner=actor.membership
    )
    await _add_overdue_task(
        db_session, organization=actor.organization, created_by=actor.membership, project=project
    )
    await db_session.commit()

    response = await client.get("/api/v1/ai/project-risk")
    assert response.status_code == 200
    row = next(r for r in response.json()["items"] if r["project_id"] == str(project.id))
    assert row["level"] == "MEDIUM"  # 1 overdue task crosses the MEDIUM threshold
    assert fake_ai_client.calls == []
    assert fake_ai_client.embed_calls == []

    for _ in range(2):
        await _add_overdue_task(
            db_session,
            organization=actor.organization,
            created_by=actor.membership,
            project=project,
        )
    await db_session.commit()

    response = await client.get("/api/v1/ai/project-risk")
    assert response.status_code == 200
    row = next(r for r in response.json()["items"] if r["project_id"] == str(project.id))
    assert row["level"] == "HIGH"  # 3 overdue tasks total now crosses the HIGH threshold
    assert fake_ai_client.calls == []
    assert fake_ai_client.embed_calls == []


async def test_narrative_is_not_regenerated_when_signals_are_unchanged(
    client: AsyncClient, fake_verifier, fake_ai_client, db_session
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.MANAGER)
    project = await make_project(
        db_session, organization=actor.organization, owner=actor.membership
    )
    await db_session.commit()
    fake_ai_client.next_response = "This project looks healthy."

    first = await client.get(f"/api/v1/projects/{project.id}/risk")
    assert first.status_code == 200
    assert len(fake_ai_client.calls) == 1
    first_narrative = first.json()["narrative"]

    second = await client.get(f"/api/v1/projects/{project.id}/risk")
    assert second.status_code == 200
    assert len(fake_ai_client.calls) == 1  # unchanged -- no second LLM call
    assert second.json()["narrative"] == first_narrative
    assert second.json()["level"] == first.json()["level"]


async def test_narrative_is_regenerated_when_signals_change(
    client: AsyncClient, fake_verifier, fake_ai_client, db_session
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.MANAGER)
    project = await make_project(
        db_session, organization=actor.organization, owner=actor.membership
    )
    await db_session.commit()

    fake_ai_client.next_response = "Looks fine for now."
    first = await client.get(f"/api/v1/projects/{project.id}/risk")
    assert first.status_code == 200
    assert len(fake_ai_client.calls) == 1

    await make_task(
        db_session,
        organization=actor.organization,
        created_by=actor.membership,
        project=project,
        due_date=date.today() - timedelta(days=1),
    )
    await db_session.commit()
    fake_ai_client.next_response = "Now overdue and needs attention."

    second = await client.get(f"/api/v1/projects/{project.id}/risk")
    assert second.status_code == 200
    assert len(fake_ai_client.calls) == 2  # signals changed -- one more LLM call
    assert second.json()["narrative"] == "Now overdue and needs attention."
    assert second.json()["level"] != first.json()["level"]


async def test_member_cannot_view_risk_for_a_project_they_are_not_a_member_of(
    client: AsyncClient, fake_verifier, fake_ai_client, db_session
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.MEMBER)
    other_user = await make_user(db_session, email=f"risk-other-{actor.organization.id}@x.com")
    other_membership = await make_membership(
        db_session, organization=actor.organization, user=other_user, role=Role.MEMBER
    )
    other_project = await make_project(
        db_session, organization=actor.organization, owner=other_membership
    )
    await db_session.commit()

    response = await client.get(f"/api/v1/projects/{other_project.id}/risk")
    assert response.status_code == 403
    assert fake_ai_client.calls == []


async def test_member_project_risk_list_excludes_a_project_they_are_not_a_member_of(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.MEMBER)
    own_project = await make_project(
        db_session, organization=actor.organization, owner=actor.membership
    )
    other_user = await make_user(db_session, email=f"risk-list-other-{actor.organization.id}@x.com")
    other_membership = await make_membership(
        db_session, organization=actor.organization, user=other_user, role=Role.MEMBER
    )
    unrelated_project = await make_project(
        db_session,
        organization=actor.organization,
        owner=other_membership,
        name="Unrelated Project",
    )
    await db_session.commit()

    response = await client.get("/api/v1/ai/project-risk")
    assert response.status_code == 200
    project_ids = {row["project_id"] for row in response.json()["items"]}
    assert str(own_project.id) in project_ids
    assert str(unrelated_project.id) not in project_ids


async def test_manager_sees_every_project_in_the_risk_list(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.MANAGER)
    other_user = await make_user(db_session, email=f"risk-mgr-{actor.organization.id}@x.com")
    other_membership = await make_membership(
        db_session, organization=actor.organization, user=other_user, role=Role.MEMBER
    )
    project = await make_project(
        db_session,
        organization=actor.organization,
        owner=other_membership,
        name="Someone Else's Project",
    )
    await db_session.commit()

    response = await client.get("/api/v1/ai/project-risk")
    assert response.status_code == 200
    project_ids = {row["project_id"] for row in response.json()["items"]}
    assert str(project.id) in project_ids


async def test_project_risk_for_another_org_project_is_404(
    client: AsyncClient, fake_verifier, fake_ai_client, db_session
) -> None:
    other_org = await make_organization(db_session)
    other_owner = await make_user(db_session, email=f"risk-org-{other_org.id}@x.com")
    other_membership = await make_membership(
        db_session, organization=other_org, user=other_owner, role=Role.OWNER
    )
    other_project = await make_project(db_session, organization=other_org, owner=other_membership)
    await db_session.commit()

    await login_as(client, fake_verifier, db_session, role=Role.ADMIN)
    response = await client.get(f"/api/v1/projects/{other_project.id}/risk")
    assert response.status_code == 404
    assert fake_ai_client.calls == []

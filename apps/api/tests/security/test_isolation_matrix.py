from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.factories import (
    PNG_1X1_BYTES,
    make_checklist_item,
    make_client,
    make_lead,
    make_membership,
    make_organization,
    make_project,
    make_task,
    make_task_attachment,
    make_task_comment,
    make_user,
)
from tests.helpers import login_as, login_as_existing
from trinol.core.authz.permissions import Role
from trinol.main import app
from trinol.platform.file_storage.deps import get_file_storage
from trinol.platform.file_storage.local import LocalFileStorage

# TESTING.md §4.3: every org-scoped route, member of org B against a
# resource in org A -> 404, never 403 and never 200. Team routes only for
# now (see test_authz_matrix.py's matching note).
#
# Phase 2 Stage 9: every work-module route below already had a single-role
# (usually ADMIN) cross-org spot-check as part of its own stage's integration
# tests (test_projects.py, test_tasks.py, test_task_comments.py, etc.) — this
# file broadens those to all four roles, the same generic property Phase 1
# Stage 11 proved for Team (a member's own role only ever affects
# permission-tier, never resource-scoping, so this shouldn't need re-proving
# per role, but TESTING.md's own rigor says assert it, not assume it). The
# activity feed's isolation (an org-wide list, not a per-resource 404) is
# covered separately in test_activity_feed.py's
# test_activity_feed_is_org_scoped — a different shape, same property.

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


async def test_every_role_in_org_b_gets_404_for_org_as_membership(
    client: AsyncClient, fake_verifier, db_session, two_orgs
) -> None:
    """Broader than the single-probe tests above: every role in org B — not
    just ADMIN — must get 404, never 403 and never 200, for a resource that
    only exists in org A (TESTING.md §4.3)."""
    org_a, org_b = two_orgs
    target = org_a.memberships[Role.MEMBER]

    for role in Role:
        await login_as_existing(
            client,
            fake_verifier,
            user=org_b.users[role],
            membership=org_b.memberships[role],
            organization=org_b.organization,
        )
        response = await client.get(f"/api/v1/memberships/{target.id}")
        assert response.status_code == 404, f"{role} in org B got {response.status_code}"


# PATCH/DELETE /projects/{id} are deliberately absent: unlike every route
# below, PROJECT_WRITE/PROJECT_DELETE are hard MANAGER+/ADMIN+ role-tier
# gates with no MEMBER-tier reachability, so a MANAGER (for DELETE) or
# MEMBER (for either) is rejected by the route dependency before the
# service's org-scoped lookup ever runs — a legitimate 403 regardless of
# which org the target project is in, not an isolation gap. Covered by the
# two dedicated, permission-appropriate-roles-only tests below instead.
_WORK_ISOLATION_ROUTES: list[tuple[str, str, dict[str, str] | None]] = [
    ("GET", "/api/v1/projects/{project_id}", None),
    ("GET", "/api/v1/projects/{project_id}/board", None),
    ("GET", "/api/v1/projects/{project_id}/members", None),
    ("GET", "/api/v1/projects/{project_id}/milestones", None),
    ("GET", "/api/v1/tasks/{task_id}", None),
    ("PATCH", "/api/v1/tasks/{task_id}", {"title": "Hijacked"}),
    ("DELETE", "/api/v1/tasks/{task_id}", None),
    ("GET", "/api/v1/tasks/{task_id}/comments", None),
    ("POST", "/api/v1/tasks/{task_id}/comments", {"body": "Hijack"}),
    ("PATCH", "/api/v1/tasks/{task_id}/comments/{comment_id}", {"body": "Hijack"}),
    ("DELETE", "/api/v1/tasks/{task_id}/comments/{comment_id}", None),
    ("GET", "/api/v1/tasks/{task_id}/checklist-items", None),
    ("POST", "/api/v1/tasks/{task_id}/checklist-items", {"label": "Hijack"}),
    ("PATCH", "/api/v1/tasks/{task_id}/checklist-items/{item_id}", {"label": "Hijack"}),
    ("DELETE", "/api/v1/tasks/{task_id}/checklist-items/{item_id}", None),
]


@pytest.mark.parametrize("method,path_template,body", _WORK_ISOLATION_ROUTES)
@pytest.mark.parametrize("role", list(Role))
async def test_work_resources_isolated_across_orgs(
    client: AsyncClient,
    fake_verifier,
    db_session,
    method: str,
    path_template: str,
    body: dict[str, str] | None,
    role: Role,
) -> None:
    """Every Phase 2 resource follows the same rule Team already
    established: a member of another org gets 404, never 403 and never 200,
    regardless of their own role. A fresh pair of orgs per case (rather than
    a shared fixture) means a route that incorrectly succeeds can't corrupt
    a later parametrized case's state."""
    org_a = await make_organization(db_session)
    owner_user = await make_user(db_session, email=f"iso-owner-{org_a.id}@x.com")
    owner = await make_membership(db_session, organization=org_a, user=owner_user, role=Role.OWNER)
    project = await make_project(db_session, organization=org_a, owner=owner)
    task = await make_task(db_session, organization=org_a, created_by=owner, project=project)
    comment = await make_task_comment(db_session, task=task, author=owner_user)
    checklist_item = await make_checklist_item(db_session, task=task)
    await db_session.commit()

    org_b = await make_organization(db_session)
    actor_user = await make_user(db_session, email=f"iso-actor-{org_b.id}-{role.value}@x.com")
    actor_membership = await make_membership(
        db_session, organization=org_b, user=actor_user, role=role
    )
    await db_session.commit()
    actor = await login_as_existing(
        client,
        fake_verifier,
        user=actor_user,
        membership=actor_membership,
        organization=org_b,
    )

    path = path_template.format(
        project_id=project.id,
        task_id=task.id,
        comment_id=comment.id,
        item_id=checklist_item.id,
    )
    headers = {"X-CSRF-Token": actor.csrf_token} if method != "GET" else {}
    response = await client.request(method, path, json=body, headers=headers)
    assert response.status_code == 404, (
        f"{method} {path} as {role} in org B got {response.status_code}"
    )


@pytest.mark.parametrize("method,body", [("PATCH", {"name": "Hijacked"}), ("DELETE", None)])
@pytest.mark.parametrize("role", [Role.ADMIN, Role.OWNER])
async def test_project_write_routes_isolated_across_orgs(
    client: AsyncClient,
    fake_verifier,
    db_session,
    method: str,
    body: dict[str, str] | None,
    role: Role,
) -> None:
    """PATCH/DELETE /projects/{id} split out from the generic table above:
    only ADMIN/OWNER hold PROJECT_DELETE at all (PROJECT_WRITE is MANAGER+,
    but testing DELETE with MANAGER would just prove MANAGER lacks
    PROJECT_DELETE, not isolation), so only these two roles' 404 is actually
    informative about cross-org scoping rather than route-level permission
    tier."""
    org_a = await make_organization(db_session)
    owner_user = await make_user(db_session, email=f"iso-pw-owner-{org_a.id}@x.com")
    owner = await make_membership(db_session, organization=org_a, user=owner_user, role=Role.OWNER)
    project = await make_project(db_session, organization=org_a, owner=owner)
    await db_session.commit()

    org_b = await make_organization(db_session)
    actor_user = await make_user(db_session, email=f"iso-pw-actor-{org_b.id}-{role.value}@x.com")
    actor_membership = await make_membership(
        db_session, organization=org_b, user=actor_user, role=role
    )
    await db_session.commit()
    actor = await login_as_existing(
        client,
        fake_verifier,
        user=actor_user,
        membership=actor_membership,
        organization=org_b,
    )

    response = await client.request(
        method,
        f"/api/v1/projects/{project.id}",
        json=body,
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == 404, (
        f"{method} /projects/{{id}} as {role} in org B got {response.status_code}"
    )


@pytest.mark.parametrize("role", list(Role))
async def test_attachment_routes_isolated_across_orgs(
    client: AsyncClient,
    fake_verifier,
    db_session,
    tmp_path,
    role: Role,
) -> None:
    """Same property as test_work_resources_isolated_across_orgs, split out
    because attachments need a real FileStorage override (ADR-0008) — upload
    is multipart, not JSON, so it doesn't fit the generic table above."""
    org_a = await make_organization(db_session)
    owner_user = await make_user(db_session, email=f"iso-attach-owner-{org_a.id}@x.com")
    owner = await make_membership(db_session, organization=org_a, user=owner_user, role=Role.OWNER)
    task = await make_task(db_session, organization=org_a, created_by=owner)
    storage = LocalFileStorage(tmp_path)
    app.dependency_overrides[get_file_storage] = lambda: storage
    try:
        attachment = await make_task_attachment(
            db_session, task=task, uploaded_by=owner, storage=storage
        )
        await db_session.commit()

        org_b = await make_organization(db_session)
        actor_user = await make_user(
            db_session, email=f"iso-attach-actor-{org_b.id}-{role.value}@x.com"
        )
        actor_membership = await make_membership(
            db_session, organization=org_b, user=actor_user, role=role
        )
        await db_session.commit()
        actor = await login_as_existing(
            client,
            fake_verifier,
            user=actor_user,
            membership=actor_membership,
            organization=org_b,
        )

        upload_response = await client.post(
            f"/api/v1/tasks/{task.id}/attachments",
            files={"file": ("receipt.png", PNG_1X1_BYTES, "image/png")},
            headers={"X-CSRF-Token": actor.csrf_token},
        )
        assert upload_response.status_code == 404, (
            f"upload as {role} in org B got {upload_response.status_code}"
        )

        download_response = await client.get(
            f"/api/v1/tasks/{task.id}/attachments/{attachment.id}/download"
        )
        assert download_response.status_code == 404, (
            f"download as {role} in org B got {download_response.status_code}"
        )

        delete_response = await client.delete(
            f"/api/v1/tasks/{task.id}/attachments/{attachment.id}",
            headers={"X-CSRF-Token": actor.csrf_token},
        )
        assert delete_response.status_code == 404, (
            f"delete as {role} in org B got {delete_response.status_code}"
        )
    finally:
        app.dependency_overrides.pop(get_file_storage, None)


# Phase 3 Stage 9. CLIENT_READ/LEAD_READ are MEMBER-tier (RBAC.md §2:
# role-threshold only, no ownership-split for CRM this phase) — every role
# reaches the service layer's org-scoped lookup, so every role's cross-org
# attempt must 404, the same generic property _WORK_ISOLATION_ROUTES proves
# for work-module routes above.
_CRM_READ_ISOLATION_ROUTES: list[str] = [
    "/api/v1/clients/{client_id}",
    "/api/v1/leads/{lead_id}",
]


@pytest.mark.parametrize("path_template", _CRM_READ_ISOLATION_ROUTES)
@pytest.mark.parametrize("role", list(Role))
async def test_crm_read_routes_isolated_across_orgs(
    client: AsyncClient,
    fake_verifier,
    db_session,
    path_template: str,
    role: Role,
) -> None:
    org_a = await make_organization(db_session)
    owner_user = await make_user(db_session, email=f"crm-iso-owner-{org_a.id}@x.com")
    owner = await make_membership(db_session, organization=org_a, user=owner_user, role=Role.OWNER)
    client_row = await make_client(db_session, organization=org_a, owner=owner)
    lead = await make_lead(
        db_session, organization=org_a, assigned_to=owner, email=f"crm-iso-{org_a.id}@x.com"
    )
    await db_session.commit()

    org_b = await make_organization(db_session)
    actor_user = await make_user(db_session, email=f"crm-iso-actor-{org_b.id}-{role.value}@x.com")
    actor_membership = await make_membership(
        db_session, organization=org_b, user=actor_user, role=role
    )
    await db_session.commit()
    await login_as_existing(
        client,
        fake_verifier,
        user=actor_user,
        membership=actor_membership,
        organization=org_b,
    )

    path = path_template.format(client_id=client_row.id, lead_id=lead.id)
    response = await client.get(path)
    assert response.status_code == 404, f"GET {path} as {role} in org B got {response.status_code}"


# PATCH/DELETE /clients/{id}, PATCH/DELETE /leads/{id}, and POST /leads/
# {id}/convert are deliberately absent from the generic table above: unlike
# work-module routes, CLIENT_WRITE/LEAD_WRITE/LEAD_CONVERT have no
# MEMBER-reachable path at all (RBAC.md §2's role-threshold-only design,
# Phase 3 Context decision — no ownership-split rule for CRM). Testing
# MEMBER here would only prove MEMBER lacks the permission, not prove
# isolation — same reasoning test_project_write_routes_isolated_across_orgs
# already established for PROJECT_DELETE.
_CRM_WRITE_ISOLATION_ROUTES: list[tuple[str, str, dict[str, str] | None]] = [
    ("PATCH", "/api/v1/clients/{client_id}", {"name": "Hijacked"}),
    ("DELETE", "/api/v1/clients/{client_id}", None),
    ("PATCH", "/api/v1/leads/{lead_id}", {"notes": "Hijacked"}),
    ("DELETE", "/api/v1/leads/{lead_id}", None),
    ("POST", "/api/v1/leads/{lead_id}/convert", None),
]


@pytest.mark.parametrize("method,path_template,body", _CRM_WRITE_ISOLATION_ROUTES)
@pytest.mark.parametrize("role", [Role.MANAGER, Role.ADMIN, Role.OWNER])
async def test_crm_write_routes_isolated_across_orgs(
    client: AsyncClient,
    fake_verifier,
    db_session,
    method: str,
    path_template: str,
    body: dict[str, str] | None,
    role: Role,
) -> None:
    org_a = await make_organization(db_session)
    owner_user = await make_user(db_session, email=f"crm-iso-w-owner-{org_a.id}@x.com")
    owner = await make_membership(db_session, organization=org_a, user=owner_user, role=Role.OWNER)
    client_row = await make_client(db_session, organization=org_a, owner=owner)
    lead = await make_lead(
        db_session, organization=org_a, assigned_to=owner, email=f"crm-iso-w-{org_a.id}@x.com"
    )
    await db_session.commit()

    org_b = await make_organization(db_session)
    actor_user = await make_user(db_session, email=f"crm-iso-w-actor-{org_b.id}-{role.value}@x.com")
    actor_membership = await make_membership(
        db_session, organization=org_b, user=actor_user, role=role
    )
    await db_session.commit()
    actor = await login_as_existing(
        client,
        fake_verifier,
        user=actor_user,
        membership=actor_membership,
        organization=org_b,
    )

    path = path_template.format(client_id=client_row.id, lead_id=lead.id)
    response = await client.request(
        method, path, json=body, headers={"X-CSRF-Token": actor.csrf_token}
    )
    assert response.status_code == 404, (
        f"{method} {path} as {role} in org B got {response.status_code}"
    )

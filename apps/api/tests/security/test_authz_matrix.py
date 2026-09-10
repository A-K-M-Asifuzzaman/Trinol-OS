from __future__ import annotations

import pytest
from fastapi.routing import APIRoute
from httpx import AsyncClient

from tests.factories import (
    PNG_1X1_BYTES,
    make_checklist_item,
    make_client,
    make_expense,
    make_income,
    make_invoice,
    make_lead,
    make_meeting,
    make_meeting_action,
    make_meeting_decision,
    make_meeting_participant,
    make_membership,
    make_organization,
    make_project,
    make_project_member,
    make_task,
    make_task_attachment,
    make_task_comment,
    make_user,
)
from tests.helpers import login_as, login_as_existing
from trinol.core.authz.permissions import ROLE_PERMISSIONS, Permission, Role
from trinol.core.authz.require import is_public
from trinol.core.authz.startup_audit import iter_api_routes
from trinol.main import app
from trinol.platform.file_storage.deps import get_file_storage
from trinol.platform.file_storage.local import LocalFileStorage

# RBAC.md §6: for every route x every role x own resource, assert the
# expected status.

pytestmark = pytest.mark.usefixtures("db_session")


@pytest.mark.parametrize("role", [Role.OWNER, Role.ADMIN, Role.MANAGER, Role.MEMBER])
async def test_list_team_is_readable_by_every_role(
    client: AsyncClient, fake_verifier, db_session, role: Role
) -> None:
    await login_as(client, fake_verifier, db_session, role=role)
    response = await client.get("/api/v1/memberships")
    assert response.status_code == 200


@pytest.mark.parametrize("role", [Role.OWNER, Role.ADMIN, Role.MANAGER, Role.MEMBER])
async def test_get_team_member_is_readable_by_every_role(
    client: AsyncClient, fake_verifier, db_session, role: Role
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=role)
    response = await client.get(f"/api/v1/memberships/{actor.membership.id}")
    assert response.status_code == 200


@pytest.mark.parametrize(
    ("role", "expected_status"),
    [
        (Role.OWNER, 200),
        (Role.ADMIN, 200),
        (Role.MANAGER, 403),
        (Role.MEMBER, 403),
    ],
)
async def test_role_change_requires_admin_or_owner(
    client: AsyncClient, fake_verifier, db_session, role: Role, expected_status: int
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=role)
    target_user = await make_user(db_session, email=f"target-role-{actor.organization.id}@x.com")
    target = await make_membership(
        db_session, organization=actor.organization, user=target_user, role=Role.MEMBER
    )
    await db_session.commit()

    response = await client.patch(
        f"/api/v1/memberships/{target.id}",
        json={"role": "MANAGER"},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == expected_status


@pytest.mark.parametrize(
    ("role", "expected_status"),
    [
        (Role.OWNER, 200),
        (Role.ADMIN, 200),
        (Role.MANAGER, 403),
        (Role.MEMBER, 403),
    ],
)
async def test_removal_requires_admin_or_owner(
    client: AsyncClient, fake_verifier, db_session, role: Role, expected_status: int
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=role)
    target_user = await make_user(db_session, email=f"target-remove-{actor.organization.id}@x.com")
    target = await make_membership(
        db_session, organization=actor.organization, user=target_user, role=Role.MEMBER
    )
    await db_session.commit()

    response = await client.patch(
        f"/api/v1/memberships/{target.id}",
        json={"status": "INACTIVE"},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == expected_status


async def test_patch_rejects_role_and_status_together(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    """Codex Stage 9 review: role and status each map to their own
    lock+commit service call (change_role, remove_member). Accepting both in
    one PATCH ran them back to back with no shared transaction — if the
    second raised, the first's mutation was already durably committed while
    the client saw one failed request. Rejected at the schema now: exactly
    one of role/status, never both."""
    actor = await login_as(client, fake_verifier, db_session, role=Role.OWNER)
    target_user = await make_user(db_session, email=f"target-both-{actor.organization.id}@x.com")
    target = await make_membership(
        db_session, organization=actor.organization, user=target_user, role=Role.MEMBER
    )
    await db_session.commit()

    response = await client.patch(
        f"/api/v1/memberships/{target.id}",
        json={"role": "MANAGER", "status": "INACTIVE"},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == 422


async def test_patch_rejects_neither_role_nor_status(
    client: AsyncClient, fake_verifier, db_session
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=Role.OWNER)
    target_user = await make_user(db_session, email=f"target-neither-{actor.organization.id}@x.com")
    target = await make_membership(
        db_session, organization=actor.organization, user=target_user, role=Role.MEMBER
    )
    await db_session.commit()

    response = await client.patch(
        f"/api/v1/memberships/{target.id}",
        json={},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == 422


# Stage 11: the formal matrix RBAC.md §6 asks for, plus the meta-assertion
# that "a new route with no row in it fails the suite" — one row per
# permission-gated route, with an example valid payload for the routes that
# need a body, so a role that legitimately holds the permission isn't
# rejected by request validation. {membership_id} is filled with a freshly
# created target membership per test, not the actor's own — PATCHing
# yourself hits change_role/remove_member's separate "can't act on your own
# membership" guard, which isn't what this matrix is testing.
_MATRIX_ROWS: list[tuple[str, str, Permission, dict[str, str] | None]] = [
    (
        "POST",
        "/api/v1/invitations",
        Permission.MEMBER_INVITE,
        {"email": "row@x.com", "role": "MEMBER"},
    ),
    ("GET", "/api/v1/invitations", Permission.MEMBER_INVITE, None),
    ("GET", "/api/v1/memberships", Permission.TEAM_READ, None),
    ("GET", "/api/v1/memberships/{membership_id}", Permission.TEAM_READ, None),
    (
        "PATCH",
        "/api/v1/memberships/{membership_id}",
        Permission.MEMBER_ROLE_WRITE,
        {"role": "MANAGER"},
    ),
    (
        "POST",
        "/api/v1/projects",
        Permission.PROJECT_WRITE,
        {"project_code": "MTX-1", "name": "Matrix Project"},
    ),
    ("GET", "/api/v1/projects", Permission.PROJECT_READ, None),
    (
        "PATCH",
        "/api/v1/projects/{project_id}",
        Permission.PROJECT_WRITE,
        {"name": "Matrix Renamed"},
    ),
    ("DELETE", "/api/v1/projects/{project_id}", Permission.PROJECT_DELETE, None),
    (
        "POST",
        "/api/v1/projects/{project_id}/milestones",
        Permission.PROJECT_WRITE,
        {"name": "Matrix Milestone"},
    ),
    (
        "POST",
        "/api/v1/tasks",
        Permission.TASK_WRITE_OWN,
        {"title": "Matrix Task"},
    ),
    # RBAC.md §2 grants TASK_READ org-wide with no additional per-resource
    # restriction (unlike Project detail) — ROADMAP.md Stage 3 decision, so
    # every role is expected to pass both task-read rows below, same as the
    # team-read rows above.
    ("GET", "/api/v1/tasks", Permission.TASK_READ, None),
    ("GET", "/api/v1/tasks/{task_id}", Permission.TASK_READ, None),
    # RBAC.md §3 documents no restriction on who may comment (ROADMAP.md
    # Stage 5 decision) — open to every role, same reasoning as task
    # creation/read above.
    (
        "POST",
        "/api/v1/tasks/{task_id}/comments",
        Permission.TASK_WRITE_OWN,
        {"body": "Matrix comment"},
    ),
    ("GET", "/api/v1/tasks/{task_id}/comments", Permission.TASK_READ, None),
    ("GET", "/api/v1/tasks/{task_id}/checklist-items", Permission.TASK_READ, None),
    # ADR-0008/ROADMAP.md Stage 6: attachments are authorized by the parent
    # task's own read rule, no separate attachment-level permission — same
    # org-wide transparency as every other task-read row above.
    ("GET", "/api/v1/tasks/{task_id}/attachments", Permission.TASK_READ, None),
    (
        "GET",
        "/api/v1/tasks/{task_id}/attachments/{attachment_id}/download",
        Permission.TASK_READ,
        None,
    ),
    # ROADMAP.md Phase 2 Stage 7: org-wide feed, no per-resource restriction
    # (MASTER_PROMPT §21's "Recent activity" dashboard widget) — reuses
    # PROJECT_READ rather than a new permission, same org-wide transparency
    # shape as the task-read rows above.
    ("GET", "/api/v1/activity", Permission.PROJECT_READ, None),
    # Phase 3 Stage 2: RBAC.md §2 "Leads & clients: view" is granted to
    # every role (no per-resource restriction, same org-wide transparency
    # shape as the task-read rows above) — "create/edit" is MANAGER+, with
    # no ownership-split rule this phase (ROADMAP.md Phase 3 Context
    # decision), so a plain per-row check is the whole story for these
    # routes, unlike project-member-write below.
    ("GET", "/api/v1/clients", Permission.CLIENT_READ, None),
    ("GET", "/api/v1/clients/{client_id}", Permission.CLIENT_READ, None),
    ("POST", "/api/v1/clients", Permission.CLIENT_WRITE, {"name": "Matrix Client"}),
    ("PATCH", "/api/v1/clients/{client_id}", Permission.CLIENT_WRITE, {"name": "Matrix Updated"}),
    ("DELETE", "/api/v1/clients/{client_id}", Permission.CLIENT_WRITE, None),
    # Phase 3 Stage 3: same shape as the client rows above — role-threshold
    # only, no ownership-split rule this phase.
    ("GET", "/api/v1/leads", Permission.LEAD_READ, None),
    ("GET", "/api/v1/leads/{lead_id}", Permission.LEAD_READ, None),
    (
        "POST",
        "/api/v1/leads",
        Permission.LEAD_WRITE,
        {"name": "Matrix Lead", "email": "matrix-lead@x.com", "source": "WEBSITE"},
    ),
    ("PATCH", "/api/v1/leads/{lead_id}", Permission.LEAD_WRITE, {"notes": "Matrix note"}),
    ("DELETE", "/api/v1/leads/{lead_id}", Permission.LEAD_WRITE, None),
    # Phase 3 Stage 4: pipeline is org-wide with no parent resource, so no
    # placeholder to resolve — same LEAD_READ role-threshold-only shape.
    ("GET", "/api/v1/pipeline", Permission.LEAD_READ, None),
    # Phase 3 Stage 5: the route lives in modules/work/routes/lead_
    # conversion.py (ARCHITECTURE.md §3 — crm must not import work, so the
    # one cross-module write lives in work), but LEAD_CONVERT is still the
    # RBAC-facing permission and the {lead_id} resolution branch above
    # already covers this row generically.
    ("POST", "/api/v1/leads/{lead_id}/convert", Permission.LEAD_CONVERT, None),
    # Phase 3 Stage 8: a static path, registered before /{lead_id} in
    # routes/leads.py — no placeholder to resolve, same LEAD_READ shape.
    ("GET", "/api/v1/leads/stats", Permission.LEAD_READ, None),
    # Phase 4 Stage 2: RBAC.md §2 "Meetings: create/edit own" and the new
    # "Meetings: view" row are both granted to every role — create and list
    # have no per-resource restriction (list is visibility-filtered, same
    # shape as list_projects, but the endpoint itself never 403s), so a
    # plain per-row check is the whole story for these two. GET/PATCH/
    # DELETE /meetings/{meeting_id} are NOT here — visibility and edit are
    # each an ownership-split rule (creator/participant/MANAGER+), covered
    # by test_meeting_routes_enforce_ownership_split below instead.
    (
        "POST",
        "/api/v1/meetings",
        Permission.MEETING_WRITE_OWN,
        {
            "title": "Matrix Meeting",
            "starts_at": "2026-01-01T10:00:00Z",
            "ends_at": "2026-01-01T11:00:00Z",
        },
    ),
    ("GET", "/api/v1/meetings", Permission.MEETING_READ, None),
    # Phase 5 Stage 2: RBAC.md §3 has no finance ownership-split rule at
    # all (unlike every module above) — FINANCE_READ/FINANCE_WRITE are
    # flat ADMIN+-tier gates, so every income route is a plain per-row
    # check, none of them belong in _OWNERSHIP_SPLIT_ROUTES.
    (
        "POST",
        "/api/v1/finance/income",
        Permission.FINANCE_WRITE,
        {
            "amount": "100.00",
            "source": "Matrix income",
            "received_on": "2026-01-01",
            "payment_method": "cash",
        },
    ),
    ("GET", "/api/v1/finance/income", Permission.FINANCE_READ, None),
    ("GET", "/api/v1/finance/income/{income_id}", Permission.FINANCE_READ, None),
    (
        "PATCH",
        "/api/v1/finance/income/{income_id}",
        Permission.FINANCE_WRITE,
        {"notes": "Matrix note"},
    ),
    ("DELETE", "/api/v1/finance/income/{income_id}", Permission.FINANCE_WRITE, None),
    # Phase 5 Stage 3: same flat-ADMIN+/no-ownership-split shape as income.
    # The receipt routes' bodies are multipart, not JSON — passing `body=
    # None` still exercises the row correctly, since require(...) (a
    # route-level dependency) rejects a forbidden role before FastAPI ever
    # gets to validating the missing multipart `file` field; a permitted
    # role instead gets a non-403 (422 for the missing file, or 404 if no
    # receipt exists yet), which the assertion below treats identically.
    (
        "POST",
        "/api/v1/finance/expenses",
        Permission.FINANCE_WRITE,
        {
            "amount": "50.00",
            "category": "OTHER",
            "description": "Matrix expense",
            "spent_on": "2026-01-01",
            "payment_method": "cash",
        },
    ),
    ("GET", "/api/v1/finance/expenses", Permission.FINANCE_READ, None),
    ("GET", "/api/v1/finance/expenses/{expense_id}", Permission.FINANCE_READ, None),
    (
        "PATCH",
        "/api/v1/finance/expenses/{expense_id}",
        Permission.FINANCE_WRITE,
        {"notes": "Matrix note"},
    ),
    ("DELETE", "/api/v1/finance/expenses/{expense_id}", Permission.FINANCE_WRITE, None),
    ("GET", "/api/v1/finance/expenses/{expense_id}/receipt", Permission.FINANCE_READ, None),
    ("POST", "/api/v1/finance/expenses/{expense_id}/receipt", Permission.FINANCE_WRITE, None),
    ("DELETE", "/api/v1/finance/expenses/{expense_id}/receipt", Permission.FINANCE_WRITE, None),
    # Phase 5 Stage 4: "Invoices: create/send" is one RBAC.md row/one
    # permission (INVOICE_WRITE) covering both create (this stage) and
    # send (Stage 5) — same flat-ADMIN+/no-ownership-split shape as
    # income/expenses.
    (
        "POST",
        "/api/v1/finance/invoices",
        Permission.INVOICE_WRITE,
        {
            "issue_date": "2026-01-01",
            "due_date": "2026-01-15",
            "items": [{"description": "Matrix item", "quantity": "1", "unit_price": "50.00"}],
        },
    ),
    ("GET", "/api/v1/finance/invoices", Permission.FINANCE_READ, None),
    ("GET", "/api/v1/finance/invoices/{invoice_id}", Permission.FINANCE_READ, None),
    (
        "PATCH",
        "/api/v1/finance/invoices/{invoice_id}",
        Permission.INVOICE_WRITE,
        {"notes": "Matrix note"},
    ),
]

# RBAC.md §3 / ROADMAP.md Phase 2 decision 6: these routes are gated at the
# route by a MEMBER-tier permission that only controls reachability — the
# real rule (MANAGER+ OR resource ownership/membership) lives in the
# service. The generic per-row assertion below ("permission in role <=> non
# -403") doesn't fit that shape: every role holds the route permission, so
# it would incorrectly assert a non-owner/non-member MEMBER must not be
# 403. These routes still need to appear here so the meta-assertion doesn't
# flag them as uncovered — the real (owner/member vs not) behavior is
# asserted by dedicated tests in test_projects.py/test_project_members.py,
# same dual-coverage pattern MEMBER_ROLE_WRITE's hand-written tests above
# already use alongside its own (non-split) matrix row.
_OWNERSHIP_SPLIT_ROUTES: set[tuple[str, str]] = {
    ("GET", "/api/v1/projects/{project_id}"),
    ("GET", "/api/v1/projects/{project_id}/members"),
    ("POST", "/api/v1/projects/{project_id}/members"),
    ("PATCH", "/api/v1/projects/{project_id}/members/{member_id}"),
    ("DELETE", "/api/v1/projects/{project_id}/members/{member_id}"),
    # Same shape (RBAC.md §3 "Project detail"): route is PROJECT_READ
    # (MEMBER-tier), service is ensure_project_visible (MANAGER+ or project
    # membership).
    ("GET", "/api/v1/projects/{project_id}/milestones"),
    # Same shape again: the Kanban board is just another view of the
    # project's own data (ROADMAP.md Stage 4).
    ("GET", "/api/v1/projects/{project_id}/board"),
    # RBAC.md §3 "Task edit": route is TASK_WRITE_OWN (MEMBER-tier), service
    # is TASK_WRITE_ANY (MANAGER+) or assignee or creator. Delete follows
    # the same rule (task_service.can_write_task's docstring, ROADMAP.md
    # Stage 3 decision).
    ("PATCH", "/api/v1/tasks/{task_id}"),
    ("DELETE", "/api/v1/tasks/{task_id}"),
    # RBAC.md §3 "Comment edit/delete: author only (ADMIN+ may delete)" —
    # route is TASK_WRITE_OWN (MEMBER-tier), service is author-only for
    # edit, author-or-ADMIN+ for delete (ROADMAP.md Stage 5).
    ("PATCH", "/api/v1/tasks/{task_id}/comments/{comment_id}"),
    ("DELETE", "/api/v1/tasks/{task_id}/comments/{comment_id}"),
    # Checklist items are task content, not independent discourse like
    # comments — they follow the same rule as task edit (can_write_task),
    # not comments' author-only rule (ROADMAP.md Stage 5 decision).
    ("POST", "/api/v1/tasks/{task_id}/checklist-items"),
    ("PATCH", "/api/v1/tasks/{task_id}/checklist-items/{item_id}"),
    ("DELETE", "/api/v1/tasks/{task_id}/checklist-items/{item_id}"),
    # Same can_write_task rule as checklist items — attachments are task
    # content too, no author concept (ROADMAP.md Stage 6 decision).
    ("POST", "/api/v1/tasks/{task_id}/attachments"),
    ("DELETE", "/api/v1/tasks/{task_id}/attachments/{attachment_id}"),
    # Phase 4 Stage 2: RBAC.md §3 "Meeting visibility"/"Meeting edit" — route
    # is MEETING_READ/MEETING_WRITE_OWN (MEMBER-tier, everyone passes),
    # service is ensure_meeting_visible (MANAGER+ or creator or participant)
    # for GET, can_write_meeting (MANAGER+ or creator only) for PATCH/DELETE.
    ("GET", "/api/v1/meetings/{meeting_id}"),
    ("PATCH", "/api/v1/meetings/{meeting_id}"),
    ("DELETE", "/api/v1/meetings/{meeting_id}"),
    # Phase 4 Stage 3: participant roster management inherits the meeting's
    # own visibility (GET) / edit (POST, DELETE) rule — same reasoning as
    # project-member-write above, MEETING_WRITE_OWN/MEETING_READ are both
    # MEMBER-tier reachability only.
    ("POST", "/api/v1/meetings/{meeting_id}/participants"),
    ("GET", "/api/v1/meetings/{meeting_id}/participants"),
    ("DELETE", "/api/v1/meetings/{meeting_id}/participants/{participant_id}"),
    # PATCH is its own three-way split (self, or can_write_meeting) — not
    # the plain creator/MANAGER+ shape the other three follow, so it gets
    # its own dedicated test below rather than sharing one with them.
    ("PATCH", "/api/v1/meetings/{meeting_id}/participants/{participant_id}"),
    # Phase 4 Stage 4: decisions/actions inherit the meeting's own
    # visibility (GET) / edit (POST, PATCH, DELETE) rule — same shape as
    # the participant roster routes above, no independent permission.
    ("POST", "/api/v1/meetings/{meeting_id}/decisions"),
    ("GET", "/api/v1/meetings/{meeting_id}/decisions"),
    ("DELETE", "/api/v1/meetings/{meeting_id}/decisions/{decision_id}"),
    ("POST", "/api/v1/meetings/{meeting_id}/actions"),
    ("GET", "/api/v1/meetings/{meeting_id}/actions"),
    ("PATCH", "/api/v1/meetings/{meeting_id}/actions/{action_id}"),
    ("DELETE", "/api/v1/meetings/{meeting_id}/actions/{action_id}"),
    # Phase 4 Stage 5: promote inherits the meeting's own edit rule too —
    # same shape as create/update/delete above.
    ("POST", "/api/v1/meetings/{meeting_id}/actions/{action_id}/promote"),
}


@pytest.mark.parametrize(
    ("method", "path_template", "body", "success_status"),
    [
        ("GET", "/api/v1/projects/{project_id}/members", None, 200),
        (
            "POST",
            "/api/v1/projects/{project_id}/members",
            {"user_id": "{add_user_id}"},
            201,
        ),
        (
            "PATCH",
            "/api/v1/projects/{project_id}/members/{member_id}",
            {"role_on_project": "LEAD"},
            200,
        ),
        ("DELETE", "/api/v1/projects/{project_id}/members/{member_id}", None, 204),
    ],
)
@pytest.mark.parametrize(
    ("access", "expected_status"),
    [("manager", None), ("owner", None), ("non_owner", 403), ("cross_org", 404)],
)
async def test_project_member_routes_enforce_ownership_split(
    client: AsyncClient,
    fake_verifier,
    db_session,
    method: str,
    path_template: str,
    body: dict[str, str] | None,
    success_status: int,
    access: str,
    expected_status: int | None,
) -> None:
    org = await make_organization(db_session)
    owner_user = await make_user(db_session, email=f"matrix-owner-{org.id}@x.com")
    owner = await make_membership(db_session, organization=org, user=owner_user, role=Role.MEMBER)
    project = await make_project(db_session, organization=org, owner=owner)

    target_user = await make_user(db_session, email=f"matrix-target-{org.id}@x.com")
    await make_membership(db_session, organization=org, user=target_user, role=Role.MEMBER)
    target_member = await make_project_member(db_session, project=project, user=target_user)
    add_user = await make_user(db_session, email=f"matrix-add-{org.id}@x.com")
    await make_membership(db_session, organization=org, user=add_user, role=Role.MEMBER)

    if access == "owner":
        actor_user, actor_membership, actor_org = owner_user, owner, org
    elif access in ("manager", "non_owner"):
        actor_user = await make_user(db_session, email=f"matrix-{access}-{org.id}@x.com")
        actor_membership = await make_membership(
            db_session,
            organization=org,
            user=actor_user,
            role=Role.MANAGER if access == "manager" else Role.MEMBER,
        )
        actor_org = org
    else:
        actor_org = await make_organization(db_session)
        actor_user = await make_user(db_session, email=f"matrix-cross-{actor_org.id}@x.com")
        actor_membership = await make_membership(
            db_session, organization=actor_org, user=actor_user, role=Role.MEMBER
        )
    await db_session.commit()

    actor = await login_as_existing(
        client,
        fake_verifier,
        user=actor_user,
        membership=actor_membership,
        organization=actor_org,
    )
    path = path_template.format(project_id=project.id, member_id=target_member.id)
    resolved_body = (
        {key: value.format(add_user_id=add_user.id) for key, value in body.items()}
        if body is not None
        else None
    )
    headers = {"X-CSRF-Token": actor.csrf_token} if method != "GET" else {}
    response = await client.request(method, path, json=resolved_body, headers=headers)
    assert response.status_code == (success_status if expected_status is None else expected_status)


@pytest.mark.parametrize(
    ("method", "body", "success_status"),
    [
        ("PATCH", {"title": "Renamed"}, 200),
        ("DELETE", None, 204),
    ],
)
@pytest.mark.parametrize(
    ("access", "expected_status"),
    [
        ("manager", None),
        ("assignee", None),
        ("creator", None),
        ("unrelated_member", 403),
        ("cross_org", 404),
    ],
)
async def test_task_write_routes_enforce_ownership_split(
    client: AsyncClient,
    fake_verifier,
    db_session,
    method: str,
    body: dict[str, str] | None,
    success_status: int,
    access: str,
    expected_status: int | None,
) -> None:
    """RBAC.md §3 'Task edit': MANAGER+ or the task's own assignee or
    creator — the same rule governs delete (ROADMAP.md Stage 3 decision).
    Covers every case the route/service split exists to distinguish, plus
    the two escape hatches (assignee vs creator) being independent of each
    other."""
    org = await make_organization(db_session)
    creator_user = await make_user(db_session, email=f"task-creator-{org.id}@x.com")
    creator = await make_membership(
        db_session, organization=org, user=creator_user, role=Role.MEMBER
    )
    assignee_user = await make_user(db_session, email=f"task-assignee-{org.id}@x.com")
    assignee = await make_membership(
        db_session, organization=org, user=assignee_user, role=Role.MEMBER
    )
    task = await make_task(db_session, organization=org, created_by=creator, assignee=assignee)

    if access == "creator":
        actor_user, actor_membership, actor_org = creator_user, creator, org
    elif access == "assignee":
        actor_user, actor_membership, actor_org = assignee_user, assignee, org
    elif access in ("manager", "unrelated_member"):
        actor_user = await make_user(db_session, email=f"task-{access}-{org.id}@x.com")
        actor_membership = await make_membership(
            db_session,
            organization=org,
            user=actor_user,
            role=Role.MANAGER if access == "manager" else Role.MEMBER,
        )
        actor_org = org
    else:
        actor_org = await make_organization(db_session)
        actor_user = await make_user(db_session, email=f"task-cross-{actor_org.id}@x.com")
        actor_membership = await make_membership(
            db_session, organization=actor_org, user=actor_user, role=Role.MEMBER
        )
    await db_session.commit()

    actor = await login_as_existing(
        client,
        fake_verifier,
        user=actor_user,
        membership=actor_membership,
        organization=actor_org,
    )
    headers = {"X-CSRF-Token": actor.csrf_token}
    response = await client.request(method, f"/api/v1/tasks/{task.id}", json=body, headers=headers)
    assert response.status_code == (success_status if expected_status is None else expected_status)


@pytest.mark.parametrize(
    ("method", "path_suffix", "body", "success_status"),
    [
        ("POST", "", {"label": "New item"}, 201),
        ("PATCH", "/{item_id}", {"label": "Renamed"}, 200),
        ("DELETE", "/{item_id}", None, 204),
    ],
)
@pytest.mark.parametrize(
    ("access", "expected_status"),
    [
        ("manager", None),
        ("assignee", None),
        ("creator", None),
        ("unrelated_member", 403),
        ("cross_org", 404),
    ],
)
async def test_checklist_item_routes_enforce_ownership_split(
    client: AsyncClient,
    fake_verifier,
    db_session,
    method: str,
    path_suffix: str,
    body: dict[str, str] | None,
    success_status: int,
    access: str,
    expected_status: int | None,
) -> None:
    """Checklist items follow the same rule as task edit (can_write_task),
    not comments' author-only rule (ROADMAP.md Stage 5 decision) — there's
    no author concept on a checklist item to hang a separate rule on."""
    org = await make_organization(db_session)
    creator_user = await make_user(db_session, email=f"checklist-creator-{org.id}@x.com")
    creator = await make_membership(
        db_session, organization=org, user=creator_user, role=Role.MEMBER
    )
    assignee_user = await make_user(db_session, email=f"checklist-assignee-{org.id}@x.com")
    assignee = await make_membership(
        db_session, organization=org, user=assignee_user, role=Role.MEMBER
    )
    task = await make_task(db_session, organization=org, created_by=creator, assignee=assignee)
    item = await make_checklist_item(db_session, task=task)

    if access == "creator":
        actor_user, actor_membership, actor_org = creator_user, creator, org
    elif access == "assignee":
        actor_user, actor_membership, actor_org = assignee_user, assignee, org
    elif access in ("manager", "unrelated_member"):
        actor_user = await make_user(db_session, email=f"checklist-{access}-{org.id}@x.com")
        actor_membership = await make_membership(
            db_session,
            organization=org,
            user=actor_user,
            role=Role.MANAGER if access == "manager" else Role.MEMBER,
        )
        actor_org = org
    else:
        actor_org = await make_organization(db_session)
        actor_user = await make_user(db_session, email=f"checklist-cross-{actor_org.id}@x.com")
        actor_membership = await make_membership(
            db_session, organization=actor_org, user=actor_user, role=Role.MEMBER
        )
    await db_session.commit()

    actor = await login_as_existing(
        client,
        fake_verifier,
        user=actor_user,
        membership=actor_membership,
        organization=actor_org,
    )
    path = f"/api/v1/tasks/{task.id}/checklist-items" + path_suffix.format(item_id=item.id)
    headers = {"X-CSRF-Token": actor.csrf_token}
    response = await client.request(method, path, json=body, headers=headers)
    assert response.status_code == (success_status if expected_status is None else expected_status)


@pytest.mark.parametrize(
    ("access", "expected_status"),
    [
        ("manager", None),
        ("assignee", None),
        ("creator", None),
        ("unrelated_member", 403),
        ("cross_org", 404),
    ],
)
async def test_attachment_upload_enforces_ownership_split(
    client: AsyncClient,
    fake_verifier,
    db_session,
    tmp_path,
    access: str,
    expected_status: int | None,
) -> None:
    """Same can_write_task rule as checklist items — attachments are task
    content too, no author concept (ROADMAP.md Stage 6 decision)."""
    org = await make_organization(db_session)
    creator_user = await make_user(db_session, email=f"attach-creator-{org.id}@x.com")
    creator = await make_membership(
        db_session, organization=org, user=creator_user, role=Role.MEMBER
    )
    assignee_user = await make_user(db_session, email=f"attach-assignee-{org.id}@x.com")
    assignee = await make_membership(
        db_session, organization=org, user=assignee_user, role=Role.MEMBER
    )
    task = await make_task(db_session, organization=org, created_by=creator, assignee=assignee)
    await db_session.commit()

    if access == "creator":
        actor_user, actor_membership, actor_org = creator_user, creator, org
    elif access == "assignee":
        actor_user, actor_membership, actor_org = assignee_user, assignee, org
    elif access in ("manager", "unrelated_member"):
        actor_user = await make_user(db_session, email=f"attach-{access}-{org.id}@x.com")
        actor_membership = await make_membership(
            db_session,
            organization=org,
            user=actor_user,
            role=Role.MANAGER if access == "manager" else Role.MEMBER,
        )
        actor_org = org
    else:
        actor_org = await make_organization(db_session)
        actor_user = await make_user(db_session, email=f"attach-cross-{actor_org.id}@x.com")
        actor_membership = await make_membership(
            db_session, organization=actor_org, user=actor_user, role=Role.MEMBER
        )
    await db_session.commit()

    actor = await login_as_existing(
        client,
        fake_verifier,
        user=actor_user,
        membership=actor_membership,
        organization=actor_org,
    )
    storage = LocalFileStorage(tmp_path)
    app.dependency_overrides[get_file_storage] = lambda: storage
    try:
        response = await client.post(
            f"/api/v1/tasks/{task.id}/attachments",
            files={"file": ("receipt.png", PNG_1X1_BYTES, "image/png")},
            headers={"X-CSRF-Token": actor.csrf_token},
        )
        assert response.status_code == (201 if expected_status is None else expected_status)
    finally:
        app.dependency_overrides.pop(get_file_storage, None)


@pytest.mark.parametrize(
    ("access", "expected_status"),
    [
        ("manager", None),
        ("assignee", None),
        ("creator", None),
        ("unrelated_member", 403),
        ("cross_org", 404),
    ],
)
async def test_attachment_delete_enforces_ownership_split(
    client: AsyncClient,
    fake_verifier,
    db_session,
    tmp_path,
    access: str,
    expected_status: int | None,
) -> None:
    org = await make_organization(db_session)
    creator_user = await make_user(db_session, email=f"attach-del-creator-{org.id}@x.com")
    creator = await make_membership(
        db_session, organization=org, user=creator_user, role=Role.MEMBER
    )
    assignee_user = await make_user(db_session, email=f"attach-del-assignee-{org.id}@x.com")
    assignee = await make_membership(
        db_session, organization=org, user=assignee_user, role=Role.MEMBER
    )
    task = await make_task(db_session, organization=org, created_by=creator, assignee=assignee)
    storage = LocalFileStorage(tmp_path)
    app.dependency_overrides[get_file_storage] = lambda: storage
    attachment = await make_task_attachment(
        db_session, task=task, uploaded_by=creator, storage=storage
    )
    await db_session.commit()

    if access == "creator":
        actor_user, actor_membership, actor_org = creator_user, creator, org
    elif access == "assignee":
        actor_user, actor_membership, actor_org = assignee_user, assignee, org
    elif access in ("manager", "unrelated_member"):
        actor_user = await make_user(db_session, email=f"attach-del-{access}-{org.id}@x.com")
        actor_membership = await make_membership(
            db_session,
            organization=org,
            user=actor_user,
            role=Role.MANAGER if access == "manager" else Role.MEMBER,
        )
        actor_org = org
    else:
        actor_org = await make_organization(db_session)
        actor_user = await make_user(db_session, email=f"attach-del-cross-{actor_org.id}@x.com")
        actor_membership = await make_membership(
            db_session, organization=actor_org, user=actor_user, role=Role.MEMBER
        )
    await db_session.commit()

    actor = await login_as_existing(
        client,
        fake_verifier,
        user=actor_user,
        membership=actor_membership,
        organization=actor_org,
    )
    try:
        response = await client.delete(
            f"/api/v1/tasks/{task.id}/attachments/{attachment.id}",
            headers={"X-CSRF-Token": actor.csrf_token},
        )
        assert response.status_code == (204 if expected_status is None else expected_status)
    finally:
        app.dependency_overrides.pop(get_file_storage, None)


@pytest.mark.parametrize(
    ("method", "body", "success_status"),
    [
        ("PATCH", {"body": "Edited"}, 200),
        ("DELETE", None, 204),
    ],
)
@pytest.mark.parametrize(
    ("access", "expected_status"),
    [
        ("author", None),
        ("admin_non_author", "method_dependent"),
        ("unrelated_member", 403),
        ("cross_org", 404),
    ],
)
async def test_comment_routes_enforce_author_only_edit_admin_delete(
    client: AsyncClient,
    fake_verifier,
    db_session,
    method: str,
    body: dict[str, str] | None,
    success_status: int,
    access: str,
    expected_status,
) -> None:
    """RBAC.md §3: "Comment edit/delete: author only (ADMIN+ may delete)"
    — edit has no ADMIN+ override at all (an ADMIN who isn't the author
    still gets 403 on PATCH), unlike task edit's MANAGER+ escape hatch."""
    org = await make_organization(db_session)
    author_user = await make_user(db_session, email=f"comment-author-{org.id}@x.com")
    author = await make_membership(db_session, organization=org, user=author_user, role=Role.MEMBER)
    task = await make_task(db_session, organization=org, created_by=author)
    comment = await make_task_comment(db_session, task=task, author=author_user)

    if access == "author":
        actor_user, actor_membership, actor_org = author_user, author, org
    elif access in ("admin_non_author", "unrelated_member"):
        actor_user = await make_user(db_session, email=f"comment-{access}-{org.id}@x.com")
        actor_membership = await make_membership(
            db_session,
            organization=org,
            user=actor_user,
            role=Role.ADMIN if access == "admin_non_author" else Role.MEMBER,
        )
        actor_org = org
    else:
        actor_org = await make_organization(db_session)
        actor_user = await make_user(db_session, email=f"comment-cross-{actor_org.id}@x.com")
        actor_membership = await make_membership(
            db_session, organization=actor_org, user=actor_user, role=Role.MEMBER
        )
    await db_session.commit()

    actor = await login_as_existing(
        client,
        fake_verifier,
        user=actor_user,
        membership=actor_membership,
        organization=actor_org,
    )
    # admin_non_author is the one case where edit and delete diverge:
    # ADMIN+ may delete a comment they didn't write, but may not edit it.
    if expected_status == "method_dependent":
        resolved_expected = 403 if method == "PATCH" else 204
    else:
        resolved_expected = success_status if expected_status is None else expected_status
    headers = {"X-CSRF-Token": actor.csrf_token}
    response = await client.request(
        method, f"/api/v1/tasks/{task.id}/comments/{comment.id}", json=body, headers=headers
    )
    assert response.status_code == resolved_expected


@pytest.mark.parametrize("suffix", ["milestones", "board"])
@pytest.mark.parametrize(
    ("access", "expected_status"),
    [("manager", 200), ("member", 200), ("outsider", 403), ("cross_org", 404)],
)
async def test_project_subresource_reads_enforce_project_visibility(
    client: AsyncClient, fake_verifier, db_session, access: str, expected_status: int, suffix: str
) -> None:
    """Same shape as 'Project detail' (RBAC.md §3): route is PROJECT_READ
    (MEMBER-tier), service is ensure_project_visible (MANAGER+ or project
    membership) — the Kanban board (Stage 4) is just another read view of
    the project, same rule as milestones (Stage 3)."""
    org = await make_organization(db_session)
    owner_user = await make_user(db_session, email=f"milestone-owner-{org.id}@x.com")
    owner = await make_membership(db_session, organization=org, user=owner_user, role=Role.OWNER)
    project = await make_project(db_session, organization=org, owner=owner)

    if access == "manager":
        actor_user = await make_user(db_session, email=f"milestone-manager-{org.id}@x.com")
        actor_membership = await make_membership(
            db_session, organization=org, user=actor_user, role=Role.MANAGER
        )
        actor_org = org
    elif access == "member":
        actor_user = await make_user(db_session, email=f"milestone-member-{org.id}@x.com")
        actor_membership = await make_membership(
            db_session, organization=org, user=actor_user, role=Role.MEMBER
        )
        await make_project_member(db_session, project=project, user=actor_user)
        actor_org = org
    elif access == "outsider":
        actor_user = await make_user(db_session, email=f"milestone-outsider-{org.id}@x.com")
        actor_membership = await make_membership(
            db_session, organization=org, user=actor_user, role=Role.MEMBER
        )
        actor_org = org
    else:
        actor_org = await make_organization(db_session)
        actor_user = await make_user(db_session, email=f"milestone-cross-{actor_org.id}@x.com")
        actor_membership = await make_membership(
            db_session, organization=actor_org, user=actor_user, role=Role.MEMBER
        )
    await db_session.commit()

    await login_as_existing(
        client,
        fake_verifier,
        user=actor_user,
        membership=actor_membership,
        organization=actor_org,
    )
    response = await client.get(f"/api/v1/projects/{project.id}/{suffix}")
    assert response.status_code == expected_status


@pytest.mark.parametrize(
    ("method", "body", "success_status"),
    [
        ("GET", None, 200),
        ("PATCH", {"title": "Hijacked"}, 200),
        ("DELETE", None, 204),
    ],
)
@pytest.mark.parametrize(
    ("access", "expected_status"),
    [
        ("manager", None),
        ("creator", None),
        # A participant can view (ensure_meeting_visible), but does not
        # gain edit rights merely by being invited (can_write_meeting) —
        # so GET succeeds while PATCH/DELETE 403, unlike every other role
        # in this table which is uniform across all three methods.
        ("participant", "method_dependent"),
        ("unrelated_member", 403),
        ("cross_org", 404),
    ],
)
async def test_meeting_routes_enforce_ownership_split(
    client: AsyncClient,
    fake_verifier,
    db_session,
    method: str,
    body: dict[str, str] | None,
    success_status: int,
    access: str,
    expected_status: int | str | None,
) -> None:
    """RBAC.md §3 'Meeting visibility'/'Meeting edit': view is MANAGER+ or
    creator or participant; edit/delete is MANAGER+ or creator only."""
    org = await make_organization(db_session)
    creator_user = await make_user(db_session, email=f"meeting-creator-{org.id}-{access}@x.com")
    creator = await make_membership(
        db_session, organization=org, user=creator_user, role=Role.MEMBER
    )
    meeting = await make_meeting(db_session, organization=org, created_by=creator)

    if access == "creator":
        actor_user, actor_membership, actor_org = creator_user, creator, org
    elif access == "participant":
        actor_user = await make_user(db_session, email=f"meeting-participant-{org.id}@x.com")
        actor_membership = await make_membership(
            db_session, organization=org, user=actor_user, role=Role.MEMBER
        )
        await make_meeting_participant(db_session, meeting=meeting, user=actor_membership)
        actor_org = org
    elif access in ("manager", "unrelated_member"):
        actor_user = await make_user(db_session, email=f"meeting-{access}-{org.id}@x.com")
        actor_membership = await make_membership(
            db_session,
            organization=org,
            user=actor_user,
            role=Role.MANAGER if access == "manager" else Role.MEMBER,
        )
        actor_org = org
    else:
        actor_org = await make_organization(db_session)
        actor_user = await make_user(db_session, email=f"meeting-cross-{actor_org.id}@x.com")
        actor_membership = await make_membership(
            db_session, organization=actor_org, user=actor_user, role=Role.MEMBER
        )
    await db_session.commit()

    actor = await login_as_existing(
        client,
        fake_verifier,
        user=actor_user,
        membership=actor_membership,
        organization=actor_org,
    )
    headers = {"X-CSRF-Token": actor.csrf_token} if method != "GET" else {}
    response = await client.request(
        method, f"/api/v1/meetings/{meeting.id}", json=body, headers=headers
    )
    if expected_status == "method_dependent":
        resolved_expected = success_status if method == "GET" else 403
    else:
        resolved_expected = success_status if expected_status is None else expected_status
    assert response.status_code == resolved_expected


@pytest.mark.parametrize(
    ("method", "path_suffix", "body", "success_status"),
    [
        ("POST", "", {"external_email": "matrix-guest@example.test"}, 201),
        ("GET", "", None, 200),
        ("DELETE", "/{target_participant_id}", None, 204),
    ],
)
@pytest.mark.parametrize(
    ("access", "expected_status"),
    [
        ("manager", None),
        ("creator", None),
        # A participant can list (ensure_meeting_visible governs GET), but
        # does not gain roster-management rights merely by being invited
        # (can_write_meeting governs POST/DELETE) — same asymmetry as the
        # meeting-level test above.
        ("participant", "method_dependent"),
        ("unrelated_member", 403),
        ("cross_org", 404),
    ],
)
async def test_meeting_participant_roster_routes_enforce_ownership_split(
    client: AsyncClient,
    fake_verifier,
    db_session,
    method: str,
    path_suffix: str,
    body: dict[str, str] | None,
    success_status: int,
    access: str,
    expected_status: int | str | None,
) -> None:
    """RBAC.md §3: adding/removing a participant follows the meeting's own
    edit rule (creator or MANAGER+); listing follows the meeting's own
    visibility rule (creator, participant, or MANAGER+)."""
    org = await make_organization(db_session)
    creator_user = await make_user(db_session, email=f"roster-creator-{org.id}-{access}@x.com")
    creator = await make_membership(
        db_session, organization=org, user=creator_user, role=Role.MEMBER
    )
    meeting = await make_meeting(db_session, organization=org, created_by=creator)
    target_user = await make_user(db_session, email=f"roster-target-{org.id}-{access}@x.com")
    target_membership = await make_membership(
        db_session, organization=org, user=target_user, role=Role.MEMBER
    )
    target_participant = await make_meeting_participant(
        db_session, meeting=meeting, user=target_membership
    )

    if access == "creator":
        actor_user, actor_membership, actor_org = creator_user, creator, org
    elif access == "participant":
        actor_user = await make_user(db_session, email=f"roster-participant-{org.id}@x.com")
        actor_membership = await make_membership(
            db_session, organization=org, user=actor_user, role=Role.MEMBER
        )
        await make_meeting_participant(db_session, meeting=meeting, user=actor_membership)
        actor_org = org
    elif access in ("manager", "unrelated_member"):
        actor_user = await make_user(db_session, email=f"roster-{access}-{org.id}@x.com")
        actor_membership = await make_membership(
            db_session,
            organization=org,
            user=actor_user,
            role=Role.MANAGER if access == "manager" else Role.MEMBER,
        )
        actor_org = org
    else:
        actor_org = await make_organization(db_session)
        actor_user = await make_user(db_session, email=f"roster-cross-{actor_org.id}@x.com")
        actor_membership = await make_membership(
            db_session, organization=actor_org, user=actor_user, role=Role.MEMBER
        )
    await db_session.commit()

    actor = await login_as_existing(
        client,
        fake_verifier,
        user=actor_user,
        membership=actor_membership,
        organization=actor_org,
    )
    path = f"/api/v1/meetings/{meeting.id}/participants" + path_suffix.format(
        target_participant_id=target_participant.id
    )
    headers = {"X-CSRF-Token": actor.csrf_token} if method != "GET" else {}
    response = await client.request(method, path, json=body, headers=headers)
    if expected_status == "method_dependent":
        resolved_expected = success_status if method == "GET" else 403
    else:
        resolved_expected = success_status if expected_status is None else expected_status
    assert response.status_code == resolved_expected


@pytest.mark.parametrize(
    ("access", "expected_status"),
    [
        ("manager", 200),
        ("creator", 200),
        # The narrow self-service exception: updating your OWN response is
        # allowed regardless of can_write_meeting.
        ("self", 200),
        ("unrelated_member", 403),
        ("cross_org", 404),
    ],
)
async def test_update_participant_response_route_enforces_self_or_ownership_split(
    client: AsyncClient, fake_verifier, db_session, access: str, expected_status: int
) -> None:
    org = await make_organization(db_session)
    creator_user = await make_user(db_session, email=f"resp-creator-{org.id}-{access}@x.com")
    creator = await make_membership(
        db_session, organization=org, user=creator_user, role=Role.MEMBER
    )
    meeting = await make_meeting(db_session, organization=org, created_by=creator)
    target_user = await make_user(db_session, email=f"resp-target-{org.id}-{access}@x.com")
    target_membership = await make_membership(
        db_session, organization=org, user=target_user, role=Role.MEMBER
    )
    target_participant = await make_meeting_participant(
        db_session, meeting=meeting, user=target_membership
    )

    if access == "creator":
        actor_user, actor_membership, actor_org = creator_user, creator, org
    elif access == "self":
        actor_user, actor_membership, actor_org = target_user, target_membership, org
    elif access in ("manager", "unrelated_member"):
        actor_user = await make_user(db_session, email=f"resp-{access}-{org.id}@x.com")
        actor_membership = await make_membership(
            db_session,
            organization=org,
            user=actor_user,
            role=Role.MANAGER if access == "manager" else Role.MEMBER,
        )
        actor_org = org
    else:
        actor_org = await make_organization(db_session)
        actor_user = await make_user(db_session, email=f"resp-cross-{actor_org.id}@x.com")
        actor_membership = await make_membership(
            db_session, organization=actor_org, user=actor_user, role=Role.MEMBER
        )
    await db_session.commit()

    actor = await login_as_existing(
        client,
        fake_verifier,
        user=actor_user,
        membership=actor_membership,
        organization=actor_org,
    )
    response = await client.patch(
        f"/api/v1/meetings/{meeting.id}/participants/{target_participant.id}",
        json={"response": "ACCEPTED"},
        headers={"X-CSRF-Token": actor.csrf_token},
    )
    assert response.status_code == expected_status


@pytest.mark.parametrize(
    ("method", "path_suffix", "body", "success_status"),
    [
        ("POST", "/decisions", {"body": "Matrix decision"}, 201),
        ("GET", "/decisions", None, 200),
        ("DELETE", "/decisions/{target_decision_id}", None, 204),
        ("POST", "/actions", {"description": "Matrix action"}, 201),
        ("GET", "/actions", None, 200),
        ("PATCH", "/actions/{target_action_id}", {"description": "Renamed"}, 200),
        ("DELETE", "/actions/{target_action_id}", None, 204),
        # Phase 4 Stage 5: promote follows the exact same edit-only shape
        # (creator or MANAGER+, no participant exception) — no new
        # permission, gated by the same can_write_meeting check.
        ("POST", "/actions/{target_action_id}/promote", None, 201),
    ],
)
@pytest.mark.parametrize(
    ("access", "expected_status"),
    [
        ("manager", None),
        ("creator", None),
        # A participant can list (ensure_meeting_visible governs GET), but
        # does not gain content-management rights merely by being invited
        # (can_write_meeting governs POST/PATCH/DELETE) — same asymmetry
        # as the participant roster routes above. Unlike the participant
        # response-update route, actions' own PATCH has no self-exception:
        # only the meeting's creator or a MANAGER+ may edit an action item.
        ("participant", "method_dependent"),
        ("unrelated_member", 403),
        ("cross_org", 404),
    ],
)
async def test_meeting_decision_and_action_routes_enforce_ownership_split(
    client: AsyncClient,
    fake_verifier,
    db_session,
    method: str,
    path_suffix: str,
    body: dict[str, str] | None,
    success_status: int,
    access: str,
    expected_status: int | str | None,
) -> None:
    """RBAC.md §3: meeting decisions/actions inherit the meeting's own
    visibility (GET) / edit (POST/PATCH/DELETE) rule — no author concept,
    not comments' independent author-only rule."""
    org = await make_organization(db_session)
    creator_user = await make_user(db_session, email=f"content-creator-{org.id}-{access}@x.com")
    creator = await make_membership(
        db_session, organization=org, user=creator_user, role=Role.MEMBER
    )
    meeting = await make_meeting(db_session, organization=org, created_by=creator)
    target_decision = await make_meeting_decision(db_session, meeting=meeting, decided_by=creator)
    target_action = await make_meeting_action(db_session, meeting=meeting, owner=creator)

    if access == "creator":
        actor_user, actor_membership, actor_org = creator_user, creator, org
    elif access == "participant":
        actor_user = await make_user(db_session, email=f"content-participant-{org.id}@x.com")
        actor_membership = await make_membership(
            db_session, organization=org, user=actor_user, role=Role.MEMBER
        )
        await make_meeting_participant(db_session, meeting=meeting, user=actor_membership)
        actor_org = org
    elif access in ("manager", "unrelated_member"):
        actor_user = await make_user(db_session, email=f"content-{access}-{org.id}@x.com")
        actor_membership = await make_membership(
            db_session,
            organization=org,
            user=actor_user,
            role=Role.MANAGER if access == "manager" else Role.MEMBER,
        )
        actor_org = org
    else:
        actor_org = await make_organization(db_session)
        actor_user = await make_user(db_session, email=f"content-cross-{actor_org.id}@x.com")
        actor_membership = await make_membership(
            db_session, organization=actor_org, user=actor_user, role=Role.MEMBER
        )
    await db_session.commit()

    actor = await login_as_existing(
        client,
        fake_verifier,
        user=actor_user,
        membership=actor_membership,
        organization=actor_org,
    )
    path = f"/api/v1/meetings/{meeting.id}" + path_suffix.format(
        target_decision_id=target_decision.id, target_action_id=target_action.id
    )
    headers = {"X-CSRF-Token": actor.csrf_token} if method != "GET" else {}
    response = await client.request(method, path, json=body, headers=headers)
    if expected_status == "method_dependent":
        resolved_expected = success_status if method == "GET" else 403
    else:
        resolved_expected = success_status if expected_status is None else expected_status
    assert response.status_code == resolved_expected


def _live_permission_gated_routes() -> set[tuple[str, str]]:
    pairs: set[tuple[str, str]] = set()
    for route in iter_api_routes(app):
        if not isinstance(route, APIRoute) or is_public(route.endpoint):
            continue
        for method in route.methods or set():
            if method in ("HEAD", "OPTIONS"):
                continue
            pairs.add((method, route.path))
    return pairs


def test_matrix_covers_every_permission_gated_route() -> None:
    """RBAC.md §6: "a new route with no row in it fails the suite." Derives
    the live set of non-public routes from the app itself (the same markers
    core/authz/startup_audit.py's boot-time check reads), so a new route
    can't silently go untested the way a hand-maintained list with no
    cross-check against reality could."""
    matrix_routes = {(method, path) for method, path, _permission, _body in _MATRIX_ROWS}
    matrix_routes |= _OWNERSHIP_SPLIT_ROUTES
    missing = _live_permission_gated_routes() - matrix_routes
    assert not missing, f"Route(s) with no authz-matrix row: {sorted(missing)}"


@pytest.mark.parametrize("method,path,permission,body", _MATRIX_ROWS)
@pytest.mark.parametrize("role", list(Role))
async def test_matrix_row_respects_required_permission(
    client: AsyncClient,
    fake_verifier,
    db_session,
    tmp_path,
    role: Role,
    method: str,
    path: str,
    permission: Permission,
    body: dict[str, str] | None,
) -> None:
    actor = await login_as(client, fake_verifier, db_session, role=role)
    target_user = await make_user(db_session, email=f"matrix-target-{actor.organization.id}@x.com")
    target = await make_membership(
        db_session, organization=actor.organization, user=target_user, role=Role.MEMBER
    )
    await db_session.commit()

    resolved_path = path.replace("{membership_id}", str(target.id))
    if "{client_id}" in resolved_path:
        # CLIENT_READ/CLIENT_WRITE have no per-resource restriction (no
        # ownership-split rule this phase, ROADMAP.md Phase 3 Context
        # decision) — who owns the test client doesn't affect the
        # assertion below, same reasoning as {project_id}.
        client_row = await make_client(db_session, organization=actor.organization, owner=target)
        await db_session.commit()
        resolved_path = resolved_path.replace("{client_id}", str(client_row.id))
    if "{lead_id}" in resolved_path:
        # Same reasoning as {client_id} above — LEAD_READ/LEAD_WRITE have
        # no per-resource restriction this phase.
        lead_row = await make_lead(db_session, organization=actor.organization, assigned_to=target)
        await db_session.commit()
        resolved_path = resolved_path.replace("{lead_id}", str(lead_row.id))
    if "{project_id}" in resolved_path:
        # Every row using this placeholder (PATCH/DELETE project, POST
        # milestone) is MANAGER+-only with no ownership escape hatch, so
        # who owns the test project doesn't affect the assertion below.
        project = await make_project(db_session, organization=actor.organization, owner=target)
        await db_session.commit()
        resolved_path = resolved_path.replace("{project_id}", str(project.id))
    if "{task_id}" in resolved_path:
        # TASK_READ has no per-resource restriction (ROADMAP.md Stage 3
        # decision) — a real task proves every role can genuinely read it,
        # not just that a phantom lookup happens not to 404 into a 403.
        task = await make_task(db_session, organization=actor.organization, created_by=target)
        await db_session.commit()
        resolved_path = resolved_path.replace("{task_id}", str(task.id))
        if "{attachment_id}" in resolved_path:
            # Download is authorized by the parent task's read rule alone
            # (ADR-0008) — a real stored blob proves every role can
            # genuinely download it, not just that a phantom lookup
            # happens not to 404 into a 403.
            storage = LocalFileStorage(tmp_path)
            app.dependency_overrides[get_file_storage] = lambda: storage
            attachment = await make_task_attachment(
                db_session, task=task, uploaded_by=target, storage=storage
            )
            await db_session.commit()
            resolved_path = resolved_path.replace("{attachment_id}", str(attachment.id))
    if "{income_id}" in resolved_path:
        # FINANCE_READ/FINANCE_WRITE have no per-resource restriction (no
        # ownership-split rule for finance at all, ROADMAP.md Phase 5
        # decision 2) — who created the test income row doesn't affect the
        # assertion below, same reasoning as {client_id}/{lead_id}.
        income_row = await make_income(
            db_session, organization=actor.organization, created_by=target
        )
        await db_session.commit()
        resolved_path = resolved_path.replace("{income_id}", str(income_row.id))
    if "{expense_id}" in resolved_path:
        expense_row = await make_expense(
            db_session, organization=actor.organization, created_by=target
        )
        await db_session.commit()
        resolved_path = resolved_path.replace("{expense_id}", str(expense_row.id))
    if "{invoice_id}" in resolved_path:
        invoice_client = await make_client(
            db_session, organization=actor.organization, owner=target
        )
        invoice_row = await make_invoice(
            db_session,
            organization=actor.organization,
            client=invoice_client,
            created_by=target,
        )
        await db_session.commit()
        resolved_path = resolved_path.replace("{invoice_id}", str(invoice_row.id))

    try:
        headers = {"X-CSRF-Token": actor.csrf_token} if method != "GET" else {}
        response = await client.request(method, resolved_path, json=body, headers=headers)

        if permission in ROLE_PERMISSIONS[role]:
            assert response.status_code != 403, (
                f"{role} unexpectedly forbidden on {method} {path}: {response.text}"
            )
        else:
            assert response.status_code == 403, (
                f"{role} unexpectedly allowed on {method} {path}: {response.text}"
            )
    finally:
        app.dependency_overrides.pop(get_file_storage, None)

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from trinol.core.authz.permissions import Permission
from trinol.core.authz.require import require
from trinol.core.db.engine import get_db_session
from trinol.modules.identity.deps import get_current_membership
from trinol.modules.identity.models import Membership
from trinol.modules.work.models import Milestone, Project, ProjectMember, TaskStatus
from trinol.modules.work.routes.tasks import task_to_response
from trinol.modules.work.schemas import (
    BoardColumn,
    MilestoneCreateRequest,
    MilestoneListResponse,
    MilestoneResponse,
    ProjectBoardResponse,
    ProjectCreateRequest,
    ProjectListResponse,
    ProjectMemberAddRequest,
    ProjectMemberListResponse,
    ProjectMemberResponse,
    ProjectMemberUpdateRequest,
    ProjectResponse,
    ProjectUpdateRequest,
)
from trinol.modules.work.services.board_service import get_project_board
from trinol.modules.work.services.milestone_service import create_milestone, list_milestones
from trinol.modules.work.services.project_member_service import (
    add_project_member,
    list_project_members,
    remove_project_member,
    update_project_member,
)
from trinol.modules.work.services.project_service import (
    archive_project,
    create_project,
    get_project,
    list_projects,
    update_project,
)

router = APIRouter(prefix="/api/v1/projects", tags=["work"])


def _project_to_response(project: Project) -> ProjectResponse:
    return ProjectResponse(
        id=project.id,
        project_code=project.project_code,
        name=project.name,
        description=project.description,
        status=project.status,
        health=project.health,
        owner_id=project.owner_id,
        start_date=project.start_date,
        deadline=project.deadline,
        budget=project.budget,
        currency=project.currency,
        repository_url=project.repository_url,
        production_url=project.production_url,
        staging_url=project.staging_url,
        archived_at=project.archived_at,
        created_at=project.created_at,
        updated_at=project.updated_at,
    )


def _member_to_response(member: ProjectMember) -> ProjectMemberResponse:
    return ProjectMemberResponse(
        id=member.id,
        project_id=member.project_id,
        user_id=member.user_id,
        role_on_project=member.role_on_project,
        added_at=member.added_at,
    )


@router.post(
    "",
    response_model=ProjectResponse,
    status_code=201,
    dependencies=[Depends(require(Permission.PROJECT_WRITE))],
)
async def create_project_route(
    payload: ProjectCreateRequest,
    membership: Membership = Depends(get_current_membership),
    db: AsyncSession = Depends(get_db_session),
) -> ProjectResponse:
    project = await create_project(
        db,
        organization_id=membership.organization_id,
        actor=membership,
        project_code=payload.project_code,
        name=payload.name,
        description=payload.description,
        status=payload.status,
        health=payload.health,
        owner_id=payload.owner_id,
        start_date=payload.start_date,
        deadline=payload.deadline,
        budget=payload.budget,
        currency=payload.currency,
        repository_url=payload.repository_url,
        production_url=payload.production_url,
        staging_url=payload.staging_url,
    )
    return _project_to_response(project)


@router.get(
    "", response_model=ProjectListResponse, dependencies=[Depends(require(Permission.PROJECT_READ))]
)
async def list_projects_route(
    limit: int = Query(default=50, ge=1, le=200),  # ADR-0005: default 50, hard cap 200
    offset: int = Query(default=0, ge=0),
    membership: Membership = Depends(get_current_membership),
    db: AsyncSession = Depends(get_db_session),
) -> ProjectListResponse:
    result = await list_projects(
        db, organization_id=membership.organization_id, actor=membership, limit=limit, offset=offset
    )
    return ProjectListResponse(
        items=[_project_to_response(p) for p in result.items], total=result.total
    )


@router.get(
    "/{project_id}",
    response_model=ProjectResponse,
    dependencies=[Depends(require(Permission.PROJECT_READ))],
)
async def get_project_route(
    project_id: uuid.UUID,
    membership: Membership = Depends(get_current_membership),
    db: AsyncSession = Depends(get_db_session),
) -> ProjectResponse:
    project = await get_project(
        db, organization_id=membership.organization_id, actor=membership, project_id=project_id
    )
    return _project_to_response(project)


@router.patch(
    "/{project_id}",
    response_model=ProjectResponse,
    dependencies=[Depends(require(Permission.PROJECT_WRITE))],
)
async def update_project_route(
    project_id: uuid.UUID,
    payload: ProjectUpdateRequest,
    membership: Membership = Depends(get_current_membership),
    db: AsyncSession = Depends(get_db_session),
) -> ProjectResponse:
    updates = payload.model_dump(exclude_unset=True)
    project = await update_project(
        db,
        organization_id=membership.organization_id,
        actor=membership,
        project_id=project_id,
        updates=updates,
    )
    return _project_to_response(project)


@router.delete(
    "/{project_id}",
    response_model=ProjectResponse,
    dependencies=[Depends(require(Permission.PROJECT_DELETE))],
)
async def archive_project_route(
    project_id: uuid.UUID,
    membership: Membership = Depends(get_current_membership),
    db: AsyncSession = Depends(get_db_session),
) -> ProjectResponse:
    project = await archive_project(
        db, organization_id=membership.organization_id, actor=membership, project_id=project_id
    )
    return _project_to_response(project)


@router.post(
    "/{project_id}/members",
    response_model=ProjectMemberResponse,
    status_code=201,
    dependencies=[Depends(require(Permission.PROJECT_MEMBER_WRITE))],
)
async def add_project_member_route(
    project_id: uuid.UUID,
    payload: ProjectMemberAddRequest,
    membership: Membership = Depends(get_current_membership),
    db: AsyncSession = Depends(get_db_session),
) -> ProjectMemberResponse:
    member = await add_project_member(
        db,
        organization_id=membership.organization_id,
        actor=membership,
        project_id=project_id,
        user_id=payload.user_id,
        role_on_project=payload.role_on_project,
    )
    return _member_to_response(member)


@router.get(
    "/{project_id}/members",
    response_model=ProjectMemberListResponse,
    dependencies=[Depends(require(Permission.PROJECT_READ))],
)
async def list_project_members_route(
    project_id: uuid.UUID,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    membership: Membership = Depends(get_current_membership),
    db: AsyncSession = Depends(get_db_session),
) -> ProjectMemberListResponse:
    result = await list_project_members(
        db,
        organization_id=membership.organization_id,
        actor=membership,
        project_id=project_id,
        limit=limit,
        offset=offset,
    )
    return ProjectMemberListResponse(
        items=[_member_to_response(m) for m in result.items], total=result.total
    )


@router.patch(
    "/{project_id}/members/{member_id}",
    response_model=ProjectMemberResponse,
    dependencies=[Depends(require(Permission.PROJECT_MEMBER_WRITE))],
)
async def update_project_member_route(
    project_id: uuid.UUID,
    member_id: uuid.UUID,
    payload: ProjectMemberUpdateRequest,
    membership: Membership = Depends(get_current_membership),
    db: AsyncSession = Depends(get_db_session),
) -> ProjectMemberResponse:
    member = await update_project_member(
        db,
        organization_id=membership.organization_id,
        actor=membership,
        project_id=project_id,
        member_id=member_id,
        role_on_project=payload.role_on_project,
    )
    return _member_to_response(member)


@router.delete(
    "/{project_id}/members/{member_id}",
    status_code=204,
    dependencies=[Depends(require(Permission.PROJECT_MEMBER_WRITE))],
)
async def remove_project_member_route(
    project_id: uuid.UUID,
    member_id: uuid.UUID,
    membership: Membership = Depends(get_current_membership),
    db: AsyncSession = Depends(get_db_session),
) -> None:
    await remove_project_member(
        db,
        organization_id=membership.organization_id,
        actor=membership,
        project_id=project_id,
        member_id=member_id,
    )


def _milestone_to_response(milestone: Milestone) -> MilestoneResponse:
    return MilestoneResponse(
        id=milestone.id,
        project_id=milestone.project_id,
        name=milestone.name,
        description=milestone.description,
        due_date=milestone.due_date,
        completed_at=milestone.completed_at,
        position=milestone.position,
    )


@router.post(
    "/{project_id}/milestones",
    response_model=MilestoneResponse,
    status_code=201,
    dependencies=[Depends(require(Permission.PROJECT_WRITE))],
)
async def create_milestone_route(
    project_id: uuid.UUID,
    payload: MilestoneCreateRequest,
    membership: Membership = Depends(get_current_membership),
    db: AsyncSession = Depends(get_db_session),
) -> MilestoneResponse:
    milestone = await create_milestone(
        db,
        organization_id=membership.organization_id,
        actor=membership,
        project_id=project_id,
        name=payload.name,
        description=payload.description,
        due_date=payload.due_date,
        position=payload.position,
    )
    return _milestone_to_response(milestone)


@router.get(
    "/{project_id}/milestones",
    response_model=MilestoneListResponse,
    dependencies=[Depends(require(Permission.PROJECT_READ))],
)
async def list_milestones_route(
    project_id: uuid.UUID,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    membership: Membership = Depends(get_current_membership),
    db: AsyncSession = Depends(get_db_session),
) -> MilestoneListResponse:
    result = await list_milestones(
        db,
        organization_id=membership.organization_id,
        actor=membership,
        project_id=project_id,
        limit=limit,
        offset=offset,
    )
    return MilestoneListResponse(
        items=[_milestone_to_response(m) for m in result.items], total=result.total
    )


@router.get(
    "/{project_id}/board",
    response_model=ProjectBoardResponse,
    dependencies=[Depends(require(Permission.PROJECT_READ))],
)
async def get_project_board_route(
    project_id: uuid.UUID,
    membership: Membership = Depends(get_current_membership),
    db: AsyncSession = Depends(get_db_session),
) -> ProjectBoardResponse:
    board = await get_project_board(
        db, organization_id=membership.organization_id, actor=membership, project_id=project_id
    )
    return ProjectBoardResponse(
        columns=[
            BoardColumn(status=status, tasks=[task_to_response(t) for t in board.columns[status]])
            for status in TaskStatus
        ],
        total=board.total,
        truncated=board.truncated,
    )

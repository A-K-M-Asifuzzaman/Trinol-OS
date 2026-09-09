from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from trinol.core.authz.permissions import Permission
from trinol.core.authz.require import require
from trinol.core.db.engine import get_db_session
from trinol.modules.identity.deps import get_current_membership
from trinol.modules.identity.models import Membership
from trinol.modules.work.models import Task, TaskChecklistItem, TaskComment, TaskStatus
from trinol.modules.work.schemas import (
    TaskChecklistItemCreateRequest,
    TaskChecklistItemListResponse,
    TaskChecklistItemResponse,
    TaskChecklistItemUpdateRequest,
    TaskCommentCreateRequest,
    TaskCommentListResponse,
    TaskCommentResponse,
    TaskCommentUpdateRequest,
    TaskCreateRequest,
    TaskListResponse,
    TaskResponse,
    TaskUpdateRequest,
)
from trinol.modules.work.services.task_checklist_service import (
    create_checklist_item,
    delete_checklist_item,
    list_checklist_items,
    update_checklist_item,
)
from trinol.modules.work.services.task_comment_service import (
    create_comment,
    delete_comment,
    list_comments,
    update_comment,
)
from trinol.modules.work.services.task_service import (
    create_task,
    delete_task,
    get_task,
    list_tasks,
    update_task,
)

router = APIRouter(prefix="/api/v1/tasks", tags=["work"])


def task_to_response(task: Task) -> TaskResponse:
    return TaskResponse(
        id=task.id,
        project_id=task.project_id,
        title=task.title,
        description=task.description,
        status=task.status,
        priority=task.priority,
        assignee_id=task.assignee_id,
        created_by=task.created_by,
        milestone_id=task.milestone_id,
        due_date=task.due_date,
        start_date=task.start_date,
        estimated_hours=task.estimated_hours,
        actual_hours=task.actual_hours,
        tags=task.tags,
        board_position=task.board_position,
        completed_at=task.completed_at,
        created_at=task.created_at,
        updated_at=task.updated_at,
    )


@router.post(
    "",
    response_model=TaskResponse,
    status_code=201,
    dependencies=[Depends(require(Permission.TASK_WRITE_OWN))],
)
async def create_task_route(
    payload: TaskCreateRequest,
    membership: Membership = Depends(get_current_membership),
    db: AsyncSession = Depends(get_db_session),
) -> TaskResponse:
    task = await create_task(
        db,
        organization_id=membership.organization_id,
        actor=membership,
        project_id=payload.project_id,
        title=payload.title,
        description=payload.description,
        status=payload.status,
        priority=payload.priority,
        assignee_id=payload.assignee_id,
        milestone_id=payload.milestone_id,
        due_date=payload.due_date,
        start_date=payload.start_date,
        estimated_hours=payload.estimated_hours,
        actual_hours=payload.actual_hours,
        tags=payload.tags,
    )
    return task_to_response(task)


@router.get(
    "", response_model=TaskListResponse, dependencies=[Depends(require(Permission.TASK_READ))]
)
async def list_tasks_route(
    project_id: uuid.UUID | None = None,
    assignee_id: uuid.UUID | None = None,
    status: TaskStatus | None = None,
    limit: int = Query(default=50, ge=1, le=200),  # ADR-0005: default 50, hard cap 200
    offset: int = Query(default=0, ge=0),
    membership: Membership = Depends(get_current_membership),
    db: AsyncSession = Depends(get_db_session),
) -> TaskListResponse:
    result = await list_tasks(
        db,
        organization_id=membership.organization_id,
        actor=membership,
        project_id=project_id,
        assignee_id=assignee_id,
        status=status,
        limit=limit,
        offset=offset,
    )
    return TaskListResponse(items=[task_to_response(t) for t in result.items], total=result.total)


@router.get(
    "/{task_id}",
    response_model=TaskResponse,
    dependencies=[Depends(require(Permission.TASK_READ))],
)
async def get_task_route(
    task_id: uuid.UUID,
    membership: Membership = Depends(get_current_membership),
    db: AsyncSession = Depends(get_db_session),
) -> TaskResponse:
    task = await get_task(
        db, organization_id=membership.organization_id, actor=membership, task_id=task_id
    )
    return task_to_response(task)


@router.patch(
    "/{task_id}",
    response_model=TaskResponse,
    dependencies=[Depends(require(Permission.TASK_WRITE_OWN))],
)
async def update_task_route(
    task_id: uuid.UUID,
    payload: TaskUpdateRequest,
    membership: Membership = Depends(get_current_membership),
    db: AsyncSession = Depends(get_db_session),
) -> TaskResponse:
    updates = payload.model_dump(exclude_unset=True)
    task = await update_task(
        db,
        organization_id=membership.organization_id,
        actor=membership,
        task_id=task_id,
        updates=updates,
    )
    return task_to_response(task)


@router.delete(
    "/{task_id}", status_code=204, dependencies=[Depends(require(Permission.TASK_WRITE_OWN))]
)
async def delete_task_route(
    task_id: uuid.UUID,
    membership: Membership = Depends(get_current_membership),
    db: AsyncSession = Depends(get_db_session),
) -> None:
    await delete_task(
        db, organization_id=membership.organization_id, actor=membership, task_id=task_id
    )


def _comment_to_response(comment: TaskComment) -> TaskCommentResponse:
    return TaskCommentResponse(
        id=comment.id,
        task_id=comment.task_id,
        author_id=comment.author_id,
        body=comment.body,
        edited_at=comment.edited_at,
        created_at=comment.created_at,
        updated_at=comment.updated_at,
    )


def _checklist_item_to_response(item: TaskChecklistItem) -> TaskChecklistItemResponse:
    return TaskChecklistItemResponse(
        id=item.id, task_id=item.task_id, label=item.label, done=item.done, position=item.position
    )


@router.post(
    "/{task_id}/comments",
    response_model=TaskCommentResponse,
    status_code=201,
    dependencies=[Depends(require(Permission.TASK_WRITE_OWN))],
)
async def create_comment_route(
    task_id: uuid.UUID,
    payload: TaskCommentCreateRequest,
    membership: Membership = Depends(get_current_membership),
    db: AsyncSession = Depends(get_db_session),
) -> TaskCommentResponse:
    comment = await create_comment(
        db,
        organization_id=membership.organization_id,
        actor=membership,
        task_id=task_id,
        body=payload.body,
    )
    return _comment_to_response(comment)


@router.get(
    "/{task_id}/comments",
    response_model=TaskCommentListResponse,
    dependencies=[Depends(require(Permission.TASK_READ))],
)
async def list_comments_route(
    task_id: uuid.UUID,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    membership: Membership = Depends(get_current_membership),
    db: AsyncSession = Depends(get_db_session),
) -> TaskCommentListResponse:
    result = await list_comments(
        db,
        organization_id=membership.organization_id,
        actor=membership,
        task_id=task_id,
        limit=limit,
        offset=offset,
    )
    return TaskCommentListResponse(
        items=[_comment_to_response(c) for c in result.items], total=result.total
    )


@router.patch(
    "/{task_id}/comments/{comment_id}",
    response_model=TaskCommentResponse,
    dependencies=[Depends(require(Permission.TASK_WRITE_OWN))],
)
async def update_comment_route(
    task_id: uuid.UUID,
    comment_id: uuid.UUID,
    payload: TaskCommentUpdateRequest,
    membership: Membership = Depends(get_current_membership),
    db: AsyncSession = Depends(get_db_session),
) -> TaskCommentResponse:
    comment = await update_comment(
        db,
        organization_id=membership.organization_id,
        actor=membership,
        task_id=task_id,
        comment_id=comment_id,
        body=payload.body,
    )
    return _comment_to_response(comment)


@router.delete(
    "/{task_id}/comments/{comment_id}",
    status_code=204,
    dependencies=[Depends(require(Permission.TASK_WRITE_OWN))],
)
async def delete_comment_route(
    task_id: uuid.UUID,
    comment_id: uuid.UUID,
    membership: Membership = Depends(get_current_membership),
    db: AsyncSession = Depends(get_db_session),
) -> None:
    await delete_comment(
        db,
        organization_id=membership.organization_id,
        actor=membership,
        task_id=task_id,
        comment_id=comment_id,
    )


@router.post(
    "/{task_id}/checklist-items",
    response_model=TaskChecklistItemResponse,
    status_code=201,
    dependencies=[Depends(require(Permission.TASK_WRITE_OWN))],
)
async def create_checklist_item_route(
    task_id: uuid.UUID,
    payload: TaskChecklistItemCreateRequest,
    membership: Membership = Depends(get_current_membership),
    db: AsyncSession = Depends(get_db_session),
) -> TaskChecklistItemResponse:
    item = await create_checklist_item(
        db,
        organization_id=membership.organization_id,
        actor=membership,
        task_id=task_id,
        label=payload.label,
        position=payload.position,
    )
    return _checklist_item_to_response(item)


@router.get(
    "/{task_id}/checklist-items",
    response_model=TaskChecklistItemListResponse,
    dependencies=[Depends(require(Permission.TASK_READ))],
)
async def list_checklist_items_route(
    task_id: uuid.UUID,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    membership: Membership = Depends(get_current_membership),
    db: AsyncSession = Depends(get_db_session),
) -> TaskChecklistItemListResponse:
    result = await list_checklist_items(
        db,
        organization_id=membership.organization_id,
        actor=membership,
        task_id=task_id,
        limit=limit,
        offset=offset,
    )
    return TaskChecklistItemListResponse(
        items=[_checklist_item_to_response(i) for i in result.items], total=result.total
    )


@router.patch(
    "/{task_id}/checklist-items/{item_id}",
    response_model=TaskChecklistItemResponse,
    dependencies=[Depends(require(Permission.TASK_WRITE_OWN))],
)
async def update_checklist_item_route(
    task_id: uuid.UUID,
    item_id: uuid.UUID,
    payload: TaskChecklistItemUpdateRequest,
    membership: Membership = Depends(get_current_membership),
    db: AsyncSession = Depends(get_db_session),
) -> TaskChecklistItemResponse:
    updates = payload.model_dump(exclude_unset=True)
    item = await update_checklist_item(
        db,
        organization_id=membership.organization_id,
        actor=membership,
        task_id=task_id,
        item_id=item_id,
        updates=updates,
    )
    return _checklist_item_to_response(item)


@router.delete(
    "/{task_id}/checklist-items/{item_id}",
    status_code=204,
    dependencies=[Depends(require(Permission.TASK_WRITE_OWN))],
)
async def delete_checklist_item_route(
    task_id: uuid.UUID,
    item_id: uuid.UUID,
    membership: Membership = Depends(get_current_membership),
    db: AsyncSession = Depends(get_db_session),
) -> None:
    await delete_checklist_item(
        db,
        organization_id=membership.organization_id,
        actor=membership,
        task_id=task_id,
        item_id=item_id,
    )

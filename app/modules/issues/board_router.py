from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.core.deps import get_current_user
from app.core.exceptions import AppError
from app.core.permissions import Permission, can_manage_project, ensure_project_permission
from app.modules.issues.block_service import active_blocks_for_issues
from app.modules.issues.image_service import images_for_issues
from app.modules.issues.models import Issue
from app.modules.issues.service import issue_view
from app.modules.projects.models import Project
from app.modules.workflows.models import WorkflowStatus

router = APIRouter(tags=["Board"])


@router.get("/projects/{project_id}/board")
async def board(project_id: UUID, session: AsyncSession = Depends(get_session), user=Depends(get_current_user)):
    await ensure_project_permission(session, user, project_id, Permission.PROJECT_READ)
    project = await session.scalar(select(Project).where(Project.id == project_id, Project.status == "ACTIVE"))
    if not project:
        raise AppError("NOT_FOUND", "Proyecto no encontrado", 404)

    statuses = list((await session.scalars(
        select(WorkflowStatus)
        .where(WorkflowStatus.workflow_id == project.default_workflow_id)
        .order_by(WorkflowStatus.position)
    )).all())

    manager = await can_manage_project(session, user, project_id)
    issue_filters = [Issue.project_id == project_id, Issue.deleted_at.is_(None)]
    if not manager:
        # Seguridad en backend: un integrante solo recibe tickets donde participa como responsable o revisor.
        issue_filters.append(or_(Issue.assignee_id == user.id, Issue.reviewer_id == user.id))

    ranked = (
        select(
            Issue.id.label("issue_id"),
            func.row_number().over(partition_by=Issue.status_id, order_by=Issue.rank).label("row_num"),
        )
        .where(*issue_filters)
        .subquery()
    )
    issues = list((await session.scalars(
        select(Issue)
        .join(ranked, ranked.c.issue_id == Issue.id)
        .where(ranked.c.row_num <= 100)
        .order_by(Issue.status_id, Issue.rank)
    )).unique().all())
    issue_ids = [issue.id for issue in issues]
    image_map = await images_for_issues(session, issue_ids)
    block_map = await active_blocks_for_issues(session, issue_ids)

    groups = []
    for status in statuses:
        groups.append({
            "status": {
                "id": str(status.id),
                "code": status.code,
                "name": status.name,
                "category": status.category,
                "color": status.color,
            },
            "issues": [
                issue_view(issue, image_map.get(issue.id, []), block_map.get(issue.id))
                for issue in issues
                if issue.status_id == status.id
            ],
        })
    return {"data": groups, "meta": {"scope": "all" if manager else "mine"}}

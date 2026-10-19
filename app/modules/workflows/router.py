from uuid import UUID
from fastapi import APIRouter, Depends
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_session
from app.core.deps import get_current_user
from app.core.permissions import Permission, ensure_project_permission
from app.modules.projects.models import Project
from app.modules.workflows.models import IssueType, Priority, WorkflowStatus

router = APIRouter(tags=["Catalogs"])


@router.get("/projects/{project_id}/issue-types")
async def issue_types(project_id: UUID, session: AsyncSession = Depends(get_session), user=Depends(get_current_user)):
    await ensure_project_permission(session, user, project_id, Permission.PROJECT_READ)
    rows = list((await session.scalars(select(IssueType).where(or_(IssueType.project_id.is_(None), IssueType.project_id == project_id), IssueType.is_active.is_(True)).order_by(IssueType.position))).all())
    return {"data": [{"id": str(x.id), "code": x.code, "name": x.name, "is_epic": x.is_epic, "is_subtask": x.is_subtask} for x in rows]}


@router.get("/projects/{project_id}/priorities")
async def priorities(project_id: UUID, session: AsyncSession = Depends(get_session), user=Depends(get_current_user)):
    await ensure_project_permission(session, user, project_id, Permission.PROJECT_READ)
    rows = list((await session.scalars(select(Priority).where(or_(Priority.project_id.is_(None), Priority.project_id == project_id)).order_by(Priority.rank))).all())
    return {"data": [{"id": str(x.id), "code": x.code, "name": x.name, "rank": x.rank, "color": x.color} for x in rows]}


@router.get("/projects/{project_id}/workflow")
async def workflow(project_id: UUID, session: AsyncSession = Depends(get_session), user=Depends(get_current_user)):
    await ensure_project_permission(session, user, project_id, Permission.PROJECT_READ)
    project = await session.scalar(select(Project).where(Project.id == project_id))
    rows = list((await session.scalars(select(WorkflowStatus).where(WorkflowStatus.workflow_id == project.default_workflow_id).order_by(WorkflowStatus.position))).all())
    return {"data": [{"id": str(x.id), "code": x.code, "name": x.name, "category": x.category, "position": x.position, "color": x.color, "is_initial": x.is_initial} for x in rows]}

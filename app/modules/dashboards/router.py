from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.core.deps import get_current_user
from app.core.permissions import Permission, can_manage_project, ensure_project_permission
from app.modules.issues.models import Issue, IssueBlock
from app.modules.workflows.models import WorkflowStatus

router = APIRouter(tags=["Dashboard"])


@router.get("/projects/{project_id}/dashboard")
async def dashboard(project_id: UUID, session: AsyncSession = Depends(get_session), user=Depends(get_current_user)):
    await ensure_project_permission(session, user, project_id, Permission.PROJECT_READ)
    manager = await can_manage_project(session, user, project_id)

    base = [Issue.project_id == project_id, Issue.deleted_at.is_(None)]
    if not manager:
        base.append(or_(Issue.assignee_id == user.id, Issue.reviewer_id == user.id))

    total = await session.scalar(select(func.count(Issue.id)).where(*base)) or 0
    by_category_rows = (await session.execute(
        select(WorkflowStatus.category, func.count(Issue.id))
        .join(Issue, Issue.status_id == WorkflowStatus.id)
        .where(*base)
        .group_by(WorkflowStatus.category)
    )).all()
    by_category = {k: v for k, v in by_category_rows}
    unassigned = 0 if not manager else (
        await session.scalar(select(func.count(Issue.id)).where(*base, Issue.assignee_id.is_(None))) or 0
    )
    overdue = await session.scalar(
        select(func.count(Issue.id))
        .join(WorkflowStatus, Issue.status_id == WorkflowStatus.id)
        .where(*base, WorkflowStatus.category != "DONE", Issue.due_date.is_not(None), Issue.due_date < date.today())
    ) or 0
    blocked = await session.scalar(
        select(func.count(IssueBlock.id))
        .join(Issue, Issue.id == IssueBlock.issue_id)
        .where(*base, IssueBlock.unblocked_at.is_(None))
    ) or 0
    return {
        "data": {
            "total": total,
            "todo": by_category.get("TODO", 0),
            "in_progress": by_category.get("IN_PROGRESS", 0),
            "done": by_category.get("DONE", 0),
            "unassigned": unassigned,
            "overdue": overdue,
            "blocked": blocked,
            "scope": "all" if manager else "mine",
        }
    }

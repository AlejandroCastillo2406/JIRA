from uuid import UUID
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from app.modules.issues.models import Issue


async def get_issue(session: AsyncSession, identifier: str) -> Issue | None:
    try:
        issue_id = UUID(identifier)
        where = or_(Issue.id == issue_id, Issue.issue_key == identifier.upper())
    except ValueError:
        where = Issue.issue_key == identifier.upper()
    return await session.scalar(select(Issue).where(where, Issue.deleted_at.is_(None)).execution_options(populate_existing=True))


async def list_project_issues(session: AsyncSession, project_id: UUID, *, status_id: UUID | None = None,
                              assignee_id: UUID | None = None, participant_id: UUID | None = None,
                              q: str | None = None, page: int = 1, page_size: int = 50):
    stmt = select(Issue).where(Issue.project_id == project_id, Issue.deleted_at.is_(None))
    if status_id:
        stmt = stmt.where(Issue.status_id == status_id)
    if assignee_id:
        stmt = stmt.where(Issue.assignee_id == assignee_id)
    if participant_id:
        stmt = stmt.where(or_(Issue.assignee_id == participant_id, Issue.reviewer_id == participant_id))
    if q:
        pattern = f"%{q.strip()}%"
        stmt = stmt.where(or_(Issue.issue_key.ilike(pattern), Issue.title.ilike(pattern)))
    total = await session.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = list((await session.scalars(stmt.order_by(Issue.rank, Issue.created_at).offset((page - 1) * page_size).limit(page_size))).all())
    return rows, int(total or 0)

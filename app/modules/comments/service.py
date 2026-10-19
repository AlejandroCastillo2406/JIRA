from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.audit import record_audit
from app.core.exceptions import AppError
from app.core.outbox import enqueue_event
from app.core.permissions import Permission, ensure_issue_participant, ensure_issue_visible, ensure_project_permission
from app.modules.comments.models import Comment
from app.modules.issues.repository import get_issue


def comment_view(comment: Comment) -> dict:
    return {
        "id": str(comment.id),
        "content": comment.content,
        "created_at": comment.created_at.isoformat(),
        "user": {
            "id": str(comment.user.id),
            "display_name": comment.user.display_name,
            "email": comment.user.email,
        },
    }


async def list_comments(session: AsyncSession, user, identifier: str) -> list[Comment]:
    issue = await get_issue(session, identifier)
    if not issue:
        raise AppError("NOT_FOUND", "Ticket no encontrado", 404)
    await ensure_issue_visible(session, user, issue)
    return list((await session.scalars(
        select(Comment)
        .where(Comment.issue_id == issue.id, Comment.deleted_at.is_(None))
        .order_by(Comment.created_at)
    )).all())


async def create_comment(session: AsyncSession, user, identifier: str, content: str, request_id: str | None) -> Comment:
    issue = await get_issue(session, identifier)
    if not issue:
        raise AppError("NOT_FOUND", "Ticket no encontrado", 404)
    await ensure_issue_participant(session, user, issue)
    await ensure_project_permission(session, user, issue.project_id, Permission.COMMENT_CREATE)
    comment = Comment(issue_id=issue.id, user_id=user.id, content=content.strip())
    session.add(comment)
    await session.flush()
    await record_audit(
        session,
        entity_type="issue",
        entity_id=issue.id,
        project_id=issue.project_id,
        action="COMMENT_CREATED",
        actor_user_id=user.id,
        metadata={"comment_id": str(comment.id)},
        request_id=request_id,
    )
    await enqueue_event(
        session,
        event_type="CommentCreated",
        aggregate_type="issue",
        aggregate_id=issue.id,
        payload={
            "project_id": str(issue.project_id),
            "actor_user_id": str(user.id),
            "assignee_id": str(issue.assignee_id) if issue.assignee_id else None,
            "reviewer_id": str(issue.reviewer_id) if issue.reviewer_id else None,
            "issue_key": issue.issue_key,
        },
    )
    await session.commit()
    return await session.scalar(
        select(Comment).where(Comment.id == comment.id).execution_options(populate_existing=True)
    )

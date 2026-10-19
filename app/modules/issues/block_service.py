from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError
from app.core.permissions import ensure_issue_visible
from app.modules.issues.models import IssueBlock
from app.modules.issues.repository import get_issue
from app.modules.users.models import User


def _user_view(user: User | None) -> dict | None:
    if not user:
        return None
    return {
        "id": str(user.id),
        "display_name": user.display_name,
        "email": user.email,
    }


def block_view(block: IssueBlock, users: dict[UUID, User]) -> dict:
    return {
        "id": str(block.id),
        "issue_id": str(block.issue_id),
        "reason": block.reason,
        "blocked_at": block.blocked_at.isoformat(),
        "blocked_by": _user_view(users.get(block.blocked_by_user_id)),
        "unblocked_at": block.unblocked_at.isoformat() if block.unblocked_at else None,
        "unblocked_by": _user_view(users.get(block.unblocked_by_user_id)) if block.unblocked_by_user_id else None,
        "is_active": block.unblocked_at is None,
    }


async def _users_for_blocks(session: AsyncSession, blocks: list[IssueBlock]) -> dict[UUID, User]:
    user_ids: set[UUID] = set()
    for block in blocks:
        user_ids.add(block.blocked_by_user_id)
        if block.unblocked_by_user_id:
            user_ids.add(block.unblocked_by_user_id)
    if not user_ids:
        return {}
    rows = list((await session.scalars(select(User).where(User.id.in_(user_ids)))).all())
    return {row.id: row for row in rows}


async def active_blocks_for_issues(session: AsyncSession, issue_ids: list[UUID]) -> dict[UUID, dict]:
    if not issue_ids:
        return {}
    blocks = list((await session.scalars(
        select(IssueBlock).where(
            IssueBlock.issue_id.in_(issue_ids),
            IssueBlock.unblocked_at.is_(None),
        )
    )).all())
    users = await _users_for_blocks(session, blocks)
    return {block.issue_id: block_view(block, users) for block in blocks}


async def list_block_history(session: AsyncSession, user, identifier: str) -> list[dict]:
    issue = await get_issue(session, identifier)
    if not issue:
        raise AppError("NOT_FOUND", "Ticket no encontrado", 404)
    await ensure_issue_visible(session, user, issue)
    blocks = list((await session.scalars(
        select(IssueBlock)
        .where(IssueBlock.issue_id == issue.id)
        .order_by(IssueBlock.blocked_at.desc())
    )).all())
    users = await _users_for_blocks(session, blocks)
    return [block_view(block, users) for block in blocks]

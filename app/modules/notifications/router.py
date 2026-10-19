from datetime import datetime, timezone
from uuid import UUID
from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_session
from app.core.deps import get_current_user
from app.modules.notifications.models import Notification

router = APIRouter(prefix="/notifications", tags=["Notifications"])


def view(n: Notification):
    return {"id": str(n.id), "type": n.type, "entity_type": n.entity_type, "entity_id": str(n.entity_id),
            "payload": n.payload, "read_at": n.read_at.isoformat() if n.read_at else None,
            "created_at": n.created_at.isoformat()}


@router.get("")
async def list_notifications(unread_only: bool = False, limit: int = Query(30, ge=1, le=100),
                             session: AsyncSession = Depends(get_session), user=Depends(get_current_user)):
    stmt = select(Notification).where(Notification.recipient_user_id == user.id)
    if unread_only:
        stmt = stmt.where(Notification.read_at.is_(None))
    rows = list((await session.scalars(stmt.order_by(Notification.created_at.desc()).limit(limit))).all())
    return {"data": [view(x) for x in rows]}


@router.get("/unread-count")
async def unread_count(session: AsyncSession = Depends(get_session), user=Depends(get_current_user)):
    count = await session.scalar(select(func.count(Notification.id)).where(
        Notification.recipient_user_id == user.id, Notification.read_at.is_(None)
    )) or 0
    return {"data": {"count": count}}


@router.post("/{notification_id}/read")
async def mark_read(notification_id: UUID, session: AsyncSession = Depends(get_session), user=Depends(get_current_user)):
    await session.execute(update(Notification).where(Notification.id == notification_id,
        Notification.recipient_user_id == user.id).values(read_at=datetime.now(timezone.utc)))
    await session.commit()
    return {"data": {"ok": True}}


@router.post("/read-all")
async def mark_all_read(session: AsyncSession = Depends(get_session), user=Depends(get_current_user)):
    await session.execute(update(Notification).where(Notification.recipient_user_id == user.id,
        Notification.read_at.is_(None)).values(read_at=datetime.now(timezone.utc)))
    await session.commit()
    return {"data": {"ok": True}}

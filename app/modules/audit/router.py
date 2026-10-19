from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_session
from app.core.deps import get_current_user
from app.core.exceptions import AppError
from app.core.permissions import ensure_issue_visible
from app.modules.audit.models import AuditEvent
from app.modules.issues.repository import get_issue

router = APIRouter(tags=["Audit"])


@router.get("/issues/{identifier}/history")
async def history(identifier: str, session: AsyncSession = Depends(get_session), user=Depends(get_current_user)):
    issue = await get_issue(session, identifier)
    if not issue:
        raise AppError("NOT_FOUND", "Ticket no encontrado", 404)
    await ensure_issue_visible(session, user, issue)
    rows = list((await session.scalars(select(AuditEvent).where(
        AuditEvent.entity_type == "issue", AuditEvent.entity_id == issue.id
    ).order_by(AuditEvent.created_at.desc()).limit(200))).all())
    return {"data": [{
        "id": str(x.id), "action": x.action, "field_name": x.field_name,
        "old_value": x.old_value, "new_value": x.new_value, "metadata": x.metadata_json,
        "actor_user_id": str(x.actor_user_id), "created_at": x.created_at.isoformat(),
    } for x in rows]}

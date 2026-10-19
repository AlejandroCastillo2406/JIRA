from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from app.modules.audit.models import AuditEvent


async def record_audit(
    session: AsyncSession,
    *,
    entity_type: str,
    entity_id: UUID,
    action: str,
    actor_user_id: UUID,
    project_id: UUID | None = None,
    field_name: str | None = None,
    old_value: str | None = None,
    new_value: str | None = None,
    metadata: dict | None = None,
    request_id: str | None = None,
) -> None:
    session.add(AuditEvent(
        entity_type=entity_type,
        entity_id=entity_id,
        project_id=project_id,
        action=action,
        actor_user_id=actor_user_id,
        field_name=field_name,
        old_value=old_value,
        new_value=new_value,
        metadata_json=metadata,
        request_id=request_id,
    ))

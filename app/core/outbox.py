from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.notifications.models import Notification, OutboxEvent


async def enqueue_event(session: AsyncSession, *, event_type: str, aggregate_type: str,
                        aggregate_id: UUID, payload: dict) -> None:
    """Registra el evento y crea notificaciones in-app en la misma transacción.

    Esta versión no depende de Redis ni de un worker. Se conserva outbox_events como
    historial técnico, pero el evento queda procesado inmediatamente.
    """
    event = OutboxEvent(
        event_type=event_type,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        payload=payload,
        processed_at=datetime.now(timezone.utc),
        attempts=1,
    )
    session.add(event)
    await session.flush()

    actor = payload.get("actor_user_id")
    recipients = {
        recipient
        for recipient in (payload.get("assignee_id"), payload.get("reviewer_id"))
        if recipient and recipient != actor
    }
    for recipient in recipients:
        session.add(Notification(
            recipient_user_id=UUID(recipient),
            event_id=event.id,
            type=event_type,
            entity_type=aggregate_type,
            entity_id=aggregate_id,
            payload=payload,
        ))

from datetime import datetime, timezone
from uuid import UUID
from arq import cron
from arq.connections import RedisSettings
from app.core.config import settings
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from app.core.database import SessionLocal, get_engine
from app.modules.notifications.models import Notification, OutboxEvent


async def process_outbox(ctx):
    async with SessionLocal(bind=get_engine()) as session:
        async with session.begin():
            events = list((await session.scalars(
                select(OutboxEvent).where(OutboxEvent.processed_at.is_(None))
                .order_by(OutboxEvent.created_at).limit(50).with_for_update(skip_locked=True)
            )).all())
            for event in events:
                payload = event.payload or {}
                actor = payload.get("actor_user_id")
                recipients = {x for x in [payload.get("assignee_id"), payload.get("reviewer_id")] if x and x != actor}
                try:
                    for recipient in recipients:
                        session.add(Notification(
                            recipient_user_id=UUID(recipient), event_id=event.id, type=event.event_type,
                            entity_type=event.aggregate_type, entity_id=event.aggregate_id, payload=payload,
                        ))
                    event.processed_at = datetime.now(timezone.utc)
                    event.attempts += 1
                except Exception as exc:
                    event.attempts += 1
                    event.last_error = str(exc)[:1000]


class WorkerSettings:
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    cron_jobs = [cron(process_outbox, second={0, 10, 20, 30, 40, 50})]

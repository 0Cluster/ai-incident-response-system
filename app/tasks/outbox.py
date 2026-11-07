import logging

from app.celery_app import celery_app
from app.database.session import SessionLocal
from app.outbox.service import OutboxService
from app.repositories.outbox import OutboxRepository

logger = logging.getLogger(__name__)


@celery_app.task(name="dispatch_outbox")
def dispatch_outbox(limit: int = 100) -> int:
    db = SessionLocal()
    try:
        published = OutboxService(OutboxRepository(db)).dispatch_pending(limit)
        if published:
            logger.info("Published %s outbox event(s)", published)
        return published
    finally:
        db.close()

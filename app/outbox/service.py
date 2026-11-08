from __future__ import annotations

import logging
from typing import Any

from app.models.enums import OutboxStatus
from app.repositories.outbox import OutboxMessage, OutboxRepository

logger = logging.getLogger(__name__)

# Event type -> Celery task. Imports are intentionally lazy: the dependency
# graph reaches core auth -> dependencies -> outbox before the remote task
# module has finished importing. Add new background work here and write the
# outbox row in the same transaction as the business row.
# Kept for explicit injection in tests and for embedding deployments that
# register a local task object. Normally this stays empty and resolution is
# lazy to avoid an import cycle.
TASKS: dict[str, Any] = {}


def task_for_event(event_type: str) -> Any | None:
    if event_type == "analyze_incident":
        from app.tasks.incident import analyze_incident

        return analyze_incident
    if event_type == "process_remote_result":
        from app.tasks.remote import process_remote_result

        return process_remote_result
    return None


class OutboxService:
    def __init__(self, repository: OutboxRepository):
        self.repository = repository

    @staticmethod
    def _publish(message: OutboxMessage) -> None:
        task = TASKS.get(message.event_type) or task_for_event(message.event_type)
        if task is None:
            raise ValueError(f"unknown outbox event type: {message.event_type}")
        task.delay(**message.payload)

    def dispatch_pending(self, limit: int = 100) -> int:
        """Publish due events; return the number successfully published.

        Publishing is at-least-once. If the broker accepted the message but
        marking the row failed, the event is retried and the consumer's
        idempotency checks absorb the duplicate.
        """
        self.repository.recover_stale()
        messages = self.repository.claim_batch(limit)
        published = 0

        for message in messages:
            try:
                self._publish(message)
            except Exception as exc:
                logger.exception(
                    "Failed to publish outbox event %s (%s); scheduling retry",
                    message.id,
                    message.event_type,
                )
                self.repository.mark_retry(message.id, exc)
            else:
                self.repository.mark_published(message.id)
                published += 1

        return published

    def list_events(
        self,
        status: OutboxStatus | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[Any], int]:
        return self.repository.list_events(status=status, limit=limit, offset=offset)

    def replay_event(self, event_id: int) -> bool:
        """Operator replay: mark a FAILED outbox event back to PENDING."""
        return self.repository.mark_replay(event_id)

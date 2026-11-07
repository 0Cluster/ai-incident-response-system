from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.models.enums import OutboxStatus
from app.models.outbox import OutboxEvent

MAX_ATTEMPTS = 10
BASE_BACKOFF_SECONDS = 30
MAX_BACKOFF_SECONDS = 3600
STALE_CLAIM_SECONDS = 300


def _jitter(seconds: int) -> int:
    """Add ±25% jitter to a backoff delay so thundering herds don't collide."""
    delta = max(1, int(seconds * 0.25))
    jitter = secrets.randbelow(delta * 2 + 1) - delta
    return max(1, seconds + jitter)


@dataclass(frozen=True)
class OutboxMessage:
    id: int
    event_type: str
    payload: dict


class OutboxRepository:
    def __init__(self, db: Session):
        self.db = db

    def add_event(
        self,
        event_type: str,
        payload: dict,
        idempotency_key: str,
    ) -> OutboxEvent:
        """Add an event inside the caller's transaction (no commit)."""
        event = OutboxEvent(
            event_type=event_type,
            payload=payload,
            idempotency_key=idempotency_key,
        )
        self.db.add(event)
        self.db.flush()
        return event

    def recover_stale(self) -> int:
        """Return abandoned PROCESSING claims to the pending queue."""
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(seconds=STALE_CLAIM_SECONDS)
        result = self.db.execute(
            update(OutboxEvent)
            .where(
                OutboxEvent.status == OutboxStatus.PROCESSING,
                OutboxEvent.locked_at.is_not(None),
                OutboxEvent.locked_at < cutoff,
            )
            .values(
                status=OutboxStatus.PENDING,
                locked_at=None,
                available_at=now,
                last_error="recovered stale processing claim",
            )
        )
        self.db.commit()
        return int(result.rowcount or 0)

    def claim_batch(self, limit: int = 100) -> list[OutboxMessage]:
        """Atomically claim due events; SKIP LOCKED allows safe pollers."""
        now = datetime.now(timezone.utc)
        statement = (
            select(OutboxEvent)
            .where(
                OutboxEvent.status == OutboxStatus.PENDING,
                OutboxEvent.available_at <= now,
            )
            .order_by(OutboxEvent.available_at, OutboxEvent.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        events = list(self.db.scalars(statement).all())

        messages: list[OutboxMessage] = []
        for event in events:
            event.status = OutboxStatus.PROCESSING
            event.attempts += 1
            event.locked_at = now
            messages.append(
                OutboxMessage(
                    id=event.id,
                    event_type=event.event_type,
                    payload=dict(event.payload or {}),
                )
            )

        if messages:
            self.db.commit()
        return messages

    def mark_published(self, event_id: int) -> None:
        event = self.db.get(OutboxEvent, event_id)
        if event is None:
            return
        event.status = OutboxStatus.PUBLISHED
        event.published_at = datetime.now(timezone.utc)
        event.locked_at = None
        event.last_error = None
        self.db.commit()

    def mark_retry(self, event_id: int, error: Exception | str) -> None:
        event = self.db.get(OutboxEvent, event_id)
        if event is None:
            return

        now = datetime.now(timezone.utc)
        event.locked_at = None
        event.last_error = str(error)[:4000]
        if event.attempts >= MAX_ATTEMPTS:
            event.status = OutboxStatus.FAILED
        else:
            event.status = OutboxStatus.PENDING
            delay = _jitter(
                min(
                    MAX_BACKOFF_SECONDS,
                    BASE_BACKOFF_SECONDS * (2 ** max(0, event.attempts - 1)),
                )
            )
            event.available_at = now + timedelta(seconds=delay)
        self.db.commit()

    def mark_replay(self, event_id: int) -> bool:
        """Mark a FAILED outbox event back to PENDING for operator replay."""
        event = self.db.get(OutboxEvent, event_id)
        if event is None or event.status != OutboxStatus.FAILED:
            return False
        event.status = OutboxStatus.PENDING
        event.locked_at = None
        event.last_error = None
        event.available_at = datetime.now(timezone.utc)
        self.db.commit()
        return True

    def list_events(
        self,
        status: OutboxStatus | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[OutboxEvent], int]:
        statement = select(OutboxEvent).order_by(OutboxEvent.created_at.desc())
        count_stmt = select(func.count()).select_from(OutboxEvent)
        if status is not None:
            statement = statement.where(OutboxEvent.status == status)
            count_stmt = count_stmt.where(OutboxEvent.status == status)
        total = self.db.scalar(count_stmt) or 0
        statement = statement.limit(limit).offset(offset)
        items = list(self.db.scalars(statement).all())
        return items, int(total)

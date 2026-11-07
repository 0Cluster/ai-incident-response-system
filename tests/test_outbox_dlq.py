from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.models.enums import OutboxStatus
from app.models.outbox import OutboxEvent
from app.models.tenant import Tenant
from app.repositories.outbox import OutboxRepository


def _sqlite_session_factory() -> sessionmaker:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Tenant.__table__.create(engine)
    OutboxEvent.__table__.create(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def _insert_default_tenant(db: Session) -> int:
    tenant = Tenant(slug="default", name="Default", is_active=True)
    db.add(tenant)
    db.flush()
    db.refresh(tenant)
    return tenant.id


def test_mark_retry_adds_jitter_within_bounds():
    SessionLocal = _sqlite_session_factory()
    db: Session = SessionLocal()
    try:
        _insert_default_tenant(db)
        repo = OutboxRepository(db)
        event = OutboxEvent(
            event_type="analyze_incident",
            payload={"incident_id": 1},
            idempotency_key="analyze_incident:1",
            status=OutboxStatus.PENDING,
            attempts=3,
            available_at=datetime.now(timezone.utc),
        )
        db.add(event)
        db.commit()
        db.refresh(event)

        now = datetime.now(timezone.utc).replace(tzinfo=None)
        repo.mark_retry(event.id, ConnectionError("broker down"))
        db.expire(event)
        event = db.get(OutboxEvent, event.id)

        assert event.status == OutboxStatus.PENDING
        # Base backoff for attempt 3: 30 * 2^(3-1) = 120s, jitter ±25% => 90-150s
        delta = (event.available_at - now).total_seconds()
        assert 88 <= delta <= 152, f"Expected jittered delay 88-152s, got {delta}"
    finally:
        db.close()


def test_mark_retry_terminal_failed_after_max_attempts():
    SessionLocal = _sqlite_session_factory()
    db: Session = SessionLocal()
    try:
        _insert_default_tenant(db)
        repo = OutboxRepository(db)
        event = OutboxEvent(
            event_type="analyze_incident",
            payload={"incident_id": 2},
            idempotency_key="analyze_incident:2",
            status=OutboxStatus.PENDING,
            attempts=10,
            available_at=datetime.now(timezone.utc),
        )
        db.add(event)
        db.commit()
        db.refresh(event)

        repo.mark_retry(event.id, ConnectionError("broker down"))
        db.expire(event)
        event = db.get(OutboxEvent, event.id)

        assert event.status == OutboxStatus.FAILED
    finally:
        db.close()


def test_mark_replay_failed_to_pending():
    SessionLocal = _sqlite_session_factory()
    db: Session = SessionLocal()
    try:
        _insert_default_tenant(db)
        repo = OutboxRepository(db)
        event = OutboxEvent(
            event_type="analyze_incident",
            payload={"incident_id": 3},
            idempotency_key="analyze_incident:3",
            status=OutboxStatus.FAILED,
            attempts=5,
            available_at=datetime.now(timezone.utc) - timedelta(hours=1),
            last_error="broker down",
        )
        db.add(event)
        db.commit()
        db.refresh(event)

        ok = repo.mark_replay(event.id)
        assert ok is True

        db.expire(event)
        event = db.get(OutboxEvent, event.id)
        assert event.status == OutboxStatus.PENDING
        assert event.locked_at is None
        assert event.last_error is None
        assert event.available_at >= datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=5)
    finally:
        db.close()


def test_mark_replay_non_failed_returns_false():
    SessionLocal = _sqlite_session_factory()
    db: Session = SessionLocal()
    try:
        _insert_default_tenant(db)
        repo = OutboxRepository(db)
        event = OutboxEvent(
            event_type="analyze_incident",
            payload={"incident_id": 4},
            idempotency_key="analyze_incident:4",
            status=OutboxStatus.PENDING,
            attempts=0,
        )
        db.add(event)
        db.commit()

        ok = repo.mark_replay(event.id)
        assert ok is False
    finally:
        db.close()


def test_list_events_filters_by_status():
    SessionLocal = _sqlite_session_factory()
    db: Session = SessionLocal()
    try:
        _insert_default_tenant(db)
        repo = OutboxRepository(db)

        for i, status in enumerate(
            [OutboxStatus.PENDING, OutboxStatus.PUBLISHED, OutboxStatus.FAILED]
        ):
            event = OutboxEvent(
                event_type="analyze_incident",
                payload={"incident_id": i},
                idempotency_key=f"analyze_incident:{i}",
                status=status,
                attempts=0,
            )
            db.add(event)
        db.commit()

        pending, total = repo.list_events(status=OutboxStatus.PENDING)
        assert len(pending) == 1
        assert total == 1

        failed, total = repo.list_events(status=OutboxStatus.FAILED)
        assert len(failed) == 1
        assert total == 1

        all_events, total = repo.list_events()
        assert len(all_events) == 3
        assert total == 3
    finally:
        db.close()


def test_recover_stale_claims_returns_processing_to_pending():
    """Simulate a worker crash: PROCESSING claims older than 5 min recover."""
    SessionLocal = _sqlite_session_factory()
    db: Session = SessionLocal()
    try:
        _insert_default_tenant(db)
        repo = OutboxRepository(db)
        now = datetime.now(timezone.utc)

        # Fresh PROCESSING claim (should NOT recover)
        fresh = OutboxEvent(
            event_type="analyze_incident",
            payload={"incident_id": 10},
            idempotency_key="analyze_incident:10",
            status=OutboxStatus.PROCESSING,
            attempts=1,
            locked_at=now,
            available_at=now,
        )
        # Stale PROCESSING claim (should recover to PENDING)
        stale = OutboxEvent(
            event_type="analyze_incident",
            payload={"incident_id": 11},
            idempotency_key="analyze_incident:11",
            status=OutboxStatus.PROCESSING,
            attempts=1,
            locked_at=now - timedelta(seconds=600),  # 10 min ago
            available_at=now,
        )
        db.add(fresh)
        db.add(stale)
        db.commit()

        recovered = repo.recover_stale()
        assert recovered == 1

        db.expire(fresh)
        db.expire(stale)
        fresh = db.get(OutboxEvent, fresh.id)
        stale = db.get(OutboxEvent, stale.id)

        assert fresh.status == OutboxStatus.PROCESSING  # untouched
        assert stale.status == OutboxStatus.PENDING  # recovered
        assert stale.locked_at is None
        assert "recovered stale" in (stale.last_error or "")
    finally:
        db.close()


def test_service_dispatch_pending_with_jitter_on_retry():
    """End-to-end service test: broker failure marks retry with jittered delay."""
    from app.outbox.service import OutboxService

    SessionLocal = _sqlite_session_factory()
    db: Session = SessionLocal()
    try:
        _insert_default_tenant(db)
        repo = OutboxRepository(db)
        event = OutboxEvent(
            event_type="analyze_incident",
            payload={"incident_id": 20},
            idempotency_key="analyze_incident:20",
            status=OutboxStatus.PENDING,
            attempts=1,
            available_at=datetime.now(timezone.utc),
        )
        db.add(event)
        db.commit()
        db.refresh(event)

        service = OutboxService(repo)
        task = MagicMock()
        task.delay.side_effect = ConnectionError("broker down")

        with patch("app.outbox.service.TASKS", {"analyze_incident": task}):
            count = service.dispatch_pending(limit=5)

        assert count == 0
        db.expire(event)
        event = db.get(OutboxEvent, event.id)
        assert event.status == OutboxStatus.PENDING  # retried, not failed (attempt 2)
        # Backoff for attempt 2: 30 * 2^(2-1) = 60s, jitter ±25% => 45-75s
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        delta = (event.available_at - now).total_seconds()
        assert 43 <= delta <= 77, f"Expected jittered delay 43-77s, got {delta}"
    finally:
        db.close()


def test_service_replay_event_marks_failed_pending():
    from app.outbox.service import OutboxService

    SessionLocal = _sqlite_session_factory()
    db: Session = SessionLocal()
    try:
        _insert_default_tenant(db)
        repo = OutboxRepository(db)
        event = OutboxEvent(
            event_type="analyze_incident",
            payload={"incident_id": 30},
            idempotency_key="analyze_incident:30",
            status=OutboxStatus.FAILED,
            attempts=10,
        )
        db.add(event)
        db.commit()
        db.refresh(event)

        service = OutboxService(repo)
        ok = service.replay_event(event.id)
        assert ok is True

        db.expire(event)
        event = db.get(OutboxEvent, event.id)
        assert event.status == OutboxStatus.PENDING
    finally:
        db.close()

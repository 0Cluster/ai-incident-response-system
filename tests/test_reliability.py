"""Focused at-least-once / idempotency tests for incident processing."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from celery.exceptions import Retry
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.ai.schemas import IncidentAnalysis
from app.models.enums import (
    AnalysisStatus,
    AutomationStatus,
    IncidentSource,
    IncidentStatus,
    Severity,
)
from app.models.incident import Incident
from app.models.outbox import OutboxEvent
from app.models.tenant import Tenant
from app.models.enums import OutboxStatus
from app.outbox.service import OutboxService
from app.repositories.outbox import OutboxRepository
from app.tasks.incident import analyze_incident


def _session_factory() -> sessionmaker:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Tenant.__table__.create(engine)
    Incident.__table__.create(engine)
    OutboxEvent.__table__.create(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def _seed_incident(
    SessionLocal: sessionmaker,
    *,
    analysis_status: AnalysisStatus = AnalysisStatus.PENDING,
    automation_status: AutomationStatus = AutomationStatus.PENDING,
) -> int:
    db: Session = SessionLocal()
    try:
        tenant = Tenant(slug="default", name="Default", is_active=True)
        db.add(tenant)
        db.flush()
        incident = Incident(
            tenant_id=tenant.id,
            title="Database down",
            message="primary database unavailable",
            status=IncidentStatus.OPEN,
            analysis_status=analysis_status,
            automation_status=automation_status,
            severity=Severity.HIGH,
            source=IncidentSource.MANUAL,
        )
        db.add(incident)
        db.commit()
        db.refresh(incident)
        return incident.id
    finally:
        db.close()


class FakeAnalyzer:
    def __init__(
        self,
        fail_first: bool = False,
        severity: Severity = Severity.HIGH,
    ) -> None:
        self.calls = 0
        self.fail_first = fail_first
        self.severity = severity

    def analyze(self, message: str, *, tenant_id: int | None = None):
        _ = (message, tenant_id)
        self.calls += 1
        if self.fail_first and self.calls == 1:
            raise RuntimeError("transient analyzer failure")
        return IncidentAnalysis(
            summary="Database is down",
            severity=self.severity,
            recommendation="Restart the primary database",
            sources=[],
            confidence=0.8,
            model="fake",
        )


class RecordingAutomationEngine:
    calls: list[int] = []

    def run(self, incident: Incident, db: Session) -> None:
        type(self).calls.append(incident.id)
        incident.automation_status = AutomationStatus.SUCCESS
        db.commit()


def test_broker_unavailable_leaves_outbox_event_recoverable():
    SessionLocal = _session_factory()
    db: Session = SessionLocal()
    try:
        tenant = Tenant(slug="default", name="Default", is_active=True)
        db.add(tenant)
        db.commit()
        event = OutboxEvent(
            event_type="analyze_incident",
            payload={"incident_id": 1},
            idempotency_key="analyze_incident:broker-test",
            status=OutboxStatus.PENDING,
            attempts=0,
            available_at=datetime.now(timezone.utc),
        )
        db.add(event)
        db.commit()
        db.refresh(event)

        broker = MagicMock()
        broker.delay.side_effect = ConnectionError("broker unavailable")
        with patch("app.outbox.service.TASKS", {"analyze_incident": broker}):
            published = OutboxService(OutboxRepository(db)).dispatch_pending()

        assert published == 0
        db.expire_all()
        event = db.get(OutboxEvent, event.id)
        assert event is not None
        assert event.status == OutboxStatus.PENDING
        assert event.attempts == 1
        assert event.locked_at is None
        assert "broker unavailable" in (event.last_error or "")
        assert event.available_at > datetime.now(timezone.utc).replace(tzinfo=None)

        # The event is not lost: once the backoff expires, a later dispatcher
        # can publish it successfully.
        event.available_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()
        broker.delay.side_effect = None
        with patch("app.outbox.service.TASKS", {"analyze_incident": broker}):
            published = OutboxService(OutboxRepository(db)).dispatch_pending()

        assert published == 1
        db.expire_all()
        event = db.get(OutboxEvent, event.id)
        assert event.status == OutboxStatus.PUBLISHED
        assert event.attempts == 2
        assert broker.delay.call_count == 2
    finally:
        db.close()


def test_duplicate_task_delivery_does_not_repeat_analysis_or_automation():
    SessionLocal = _session_factory()
    incident_id = _seed_incident(SessionLocal)
    analyzer = FakeAnalyzer()
    RecordingAutomationEngine.calls = []

    with (
        patch("app.tasks.incident.SessionLocal", SessionLocal),
        patch("app.tasks.incident.get_incident_analyzer", return_value=analyzer),
        patch(
            "app.tasks.incident.AutomationEngine",
            RecordingAutomationEngine,
        ),
    ):
        analyze_incident.run(incident_id)
        analyze_incident.run(incident_id)

    assert analyzer.calls == 1
    assert RecordingAutomationEngine.calls == [incident_id]

    db: Session = SessionLocal()
    try:
        incident = db.get(Incident, incident_id)
        assert incident.analysis_status == AnalysisStatus.COMPLETED
        assert incident.automation_status == AutomationStatus.SUCCESS
    finally:
        db.close()


def test_abstained_analysis_preserves_existing_severity():
    SessionLocal = _session_factory()
    incident_id = _seed_incident(SessionLocal)  # seeded as HIGH
    analyzer = FakeAnalyzer(severity=Severity.UNKNOWN)
    RecordingAutomationEngine.calls = []

    with (
        patch("app.tasks.incident.SessionLocal", SessionLocal),
        patch("app.tasks.incident.get_incident_analyzer", return_value=analyzer),
        patch(
            "app.tasks.incident.AutomationEngine",
            RecordingAutomationEngine,
        ),
    ):
        analyze_incident.run(incident_id)

    db: Session = SessionLocal()
    try:
        incident = db.get(Incident, incident_id)
        assert incident.analysis_status == AnalysisStatus.COMPLETED
        assert incident.severity == Severity.HIGH
    finally:
        db.close()


def test_failed_analysis_can_be_retried_and_recovered():
    SessionLocal = _session_factory()
    incident_id = _seed_incident(SessionLocal)
    analyzer = FakeAnalyzer(fail_first=True)
    RecordingAutomationEngine.calls = []

    with (
        patch("app.tasks.incident.SessionLocal", SessionLocal),
        patch("app.tasks.incident.get_incident_analyzer", return_value=analyzer),
        patch(
            "app.tasks.incident.AutomationEngine",
            RecordingAutomationEngine,
        ),
    ):
        with patch.object(
            analyze_incident,
            "retry",
            side_effect=Retry("retry requested"),
        ) as retry:
            with pytest.raises(Retry):
                analyze_incident.run(incident_id)
            retry.assert_called_once()

        db: Session = SessionLocal()
        try:
            incident = db.get(Incident, incident_id)
            assert incident.analysis_status == AnalysisStatus.FAILED
            assert incident.automation_status == AutomationStatus.PENDING
        finally:
            db.close()

        # A Celery retry redelivers the same task. The FAILED state makes
        # analysis eligible again; automation has not run yet.
        analyze_incident.run(incident_id)

    assert analyzer.calls == 2
    assert RecordingAutomationEngine.calls == [incident_id]

    db = SessionLocal()
    try:
        incident = db.get(Incident, incident_id)
        assert incident.analysis_status == AnalysisStatus.COMPLETED
        assert incident.automation_status == AutomationStatus.SUCCESS
    finally:
        db.close()


def test_completed_analysis_is_not_repeated_on_redelivery():
    SessionLocal = _session_factory()
    incident_id = _seed_incident(
        SessionLocal,
        analysis_status=AnalysisStatus.COMPLETED,
        automation_status=AutomationStatus.SUCCESS,
    )
    analyzer = FakeAnalyzer()

    with (
        patch("app.tasks.incident.SessionLocal", SessionLocal),
        patch("app.tasks.incident.get_incident_analyzer", return_value=analyzer),
        patch("app.tasks.incident.AutomationEngine") as engine,
    ):
        analyze_incident.run(incident_id)

    assert analyzer.calls == 0
    engine.return_value.run.assert_not_called()

    db = SessionLocal()
    try:
        incident = db.get(Incident, incident_id)
        assert incident.analysis_status == AnalysisStatus.COMPLETED
        assert incident.automation_status == AutomationStatus.SUCCESS
    finally:
        db.close()

from unittest.mock import MagicMock, patch

import pytest

from app.models.enums import (
    AnalysisStatus,
    AutomationStatus,
    Severity,
)
from app.outbox.service import OutboxService
from app.repositories.outbox import OutboxMessage
from app.schemas.incident import IncidentCreate
from app.services.incident import IncidentService
from app.tasks.incident import processing_plan


def test_dispatch_publishes_and_marks_published():
    repository = MagicMock()
    repository.claim_batch.return_value = [
        OutboxMessage(
            id=1,
            event_type="analyze_incident",
            payload={"incident_id": 7},
        )
    ]
    task = MagicMock()

    with patch.dict("app.outbox.service.TASKS", {"analyze_incident": task}):
        count = OutboxService(repository).dispatch_pending(limit=5)

    assert count == 1
    task.delay.assert_called_once_with(incident_id=7)
    repository.mark_published.assert_called_once_with(1)
    repository.mark_retry.assert_not_called()


def test_dispatch_marks_retry_when_broker_fails():
    repository = MagicMock()
    repository.claim_batch.return_value = [
        OutboxMessage(
            id=2,
            event_type="analyze_incident",
            payload={"incident_id": 8},
        )
    ]
    task = MagicMock()
    task.delay.side_effect = ConnectionError("broker down")

    with patch.dict("app.outbox.service.TASKS", {"analyze_incident": task}):
        count = OutboxService(repository).dispatch_pending(limit=5)

    assert count == 0
    repository.mark_published.assert_not_called()
    repository.mark_retry.assert_called_once()
    assert isinstance(repository.mark_retry.call_args.args[1], ConnectionError)


def test_unknown_event_is_retried_not_lost():
    repository = MagicMock()
    repository.claim_batch.return_value = [
        OutboxMessage(id=3, event_type="unknown", payload={})
    ]

    with patch.dict("app.outbox.service.TASKS", {}, clear=True):
        count = OutboxService(repository).dispatch_pending()

    assert count == 0
    repository.mark_retry.assert_called_once()
    assert isinstance(repository.mark_retry.call_args.args[1], ValueError)


def test_processing_plan_skips_fully_processed_incident():
    incident = MagicMock()
    incident.analysis_status = AnalysisStatus.COMPLETED
    incident.automation_status = AutomationStatus.SUCCESS

    assert processing_plan(incident) == (False, False)


def test_processing_plan_resumes_automation_only():
    incident = MagicMock()
    incident.analysis_status = AnalysisStatus.COMPLETED
    incident.automation_status = AutomationStatus.RUNNING

    assert processing_plan(incident) == (False, True)


def test_processing_plan_treats_definitive_automation_failure_as_terminal():
    incident = MagicMock()
    incident.analysis_status = AnalysisStatus.COMPLETED
    incident.automation_status = AutomationStatus.FAILED

    # Redelivery must not re-send external side effects after a definitive
    # automation failure; replaying those needs an explicit operator action.
    assert processing_plan(incident) == (False, False)


def test_processing_plan_reruns_unfinished_analysis():
    incident = MagicMock()
    incident.analysis_status = AnalysisStatus.RUNNING
    incident.automation_status = AutomationStatus.PENDING

    assert processing_plan(incident) == (True, True)


def test_create_incident_writes_outbox_in_same_transaction():
    db = MagicMock()
    db.add.side_effect = lambda obj: setattr(obj, "id", 42)
    repository = MagicMock()
    repository.db = db
    service = IncidentService(repository, MagicMock())
    data = IncidentCreate(
        title="Database down",
        message="primary unavailable",
        severity=Severity.HIGH,
    )

    with patch("app.services.incident.OutboxRepository") as outbox_repo:
        incident = service.create_incident(data, tenant_id=1)

    assert incident.id == 42
    db.add.assert_called_once()
    db.commit.assert_called_once()
    outbox_repo.return_value.add_event.assert_called_once()
    kwargs = outbox_repo.return_value.add_event.call_args.kwargs
    assert kwargs["event_type"] == "analyze_incident"
    assert kwargs["payload"] == {"incident_id": 42}
    assert kwargs["idempotency_key"] == "analyze_incident:42"


def test_create_incident_rolls_back_if_outbox_write_fails():
    db = MagicMock()
    db.add.side_effect = lambda obj: setattr(obj, "id", 42)
    repository = MagicMock()
    repository.db = db
    service = IncidentService(repository, MagicMock())
    data = IncidentCreate(title="Database down", message="primary unavailable")

    with patch("app.services.incident.OutboxRepository") as outbox_repo:
        outbox_repo.return_value.add_event.side_effect = RuntimeError("unique")
        with pytest.raises(RuntimeError):
            service.create_incident(data, tenant_id=1)

    db.rollback.assert_called_once()
    db.commit.assert_not_called()

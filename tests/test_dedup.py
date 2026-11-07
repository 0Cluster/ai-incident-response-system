from unittest.mock import MagicMock, patch

from sqlalchemy.exc import IntegrityError

from app.models.enums import IncidentSource, IncidentStatus, Severity
from app.webhooks.adapters.custom import CustomWebhookAdapter
from app.webhooks.schemas import CustomWebhookRequest
from app.webhooks.service import WebhookService


def make_existing(
    severity: Severity = Severity.LOW,
    occurrence_count: int = 1,
):
    incident = MagicMock()
    incident.id = 1
    incident.status = IncidentStatus.OPEN
    incident.severity = severity
    incident.occurrence_count = occurrence_count
    incident.last_seen_at = None
    return incident


def make_service(existing=None, pipeline_start=None):
    repository = MagicMock()
    repository.find_active_by_fingerprint.return_value = existing
    repository.update.side_effect = lambda incident: incident
    pipeline = MagicMock()
    if pipeline_start is not None:
        pipeline.start.side_effect = pipeline_start
    return WebhookService(pipeline, repository), repository, pipeline


def request(severity: Severity = Severity.CRITICAL) -> CustomWebhookRequest:
    return CustomWebhookRequest(
        title="Database down",
        message="primary unavailable",
        severity=severity,
        fingerprint="fp-1",
    )


def test_repeated_firing_alert_updates_existing_incident():
    existing = make_existing(severity=Severity.LOW, occurrence_count=2)
    service, repository, pipeline = make_service(existing=existing)

    with patch("app.webhooks.service.MonitoringService"):
        result = service.ingest(
            CustomWebhookAdapter(),
            request(),
            IncidentSource.CUSTOM,
            tenant_id=1,
        )

    assert result == [existing]
    assert existing.occurrence_count == 3
    assert existing.severity == Severity.CRITICAL
    assert existing.last_seen_at is not None
    repository.update.assert_called_once_with(existing)
    pipeline.start.assert_not_called()


def test_repeated_firing_alert_does_not_downgrade_severity():
    existing = make_existing(severity=Severity.CRITICAL)
    service, _, _ = make_service(existing=existing)

    with patch("app.webhooks.service.MonitoringService"):
        service.ingest(
            CustomWebhookAdapter(),
            request(Severity.LOW),
            IncidentSource.CUSTOM,
            tenant_id=1,
        )

    assert existing.severity == Severity.CRITICAL


def test_concurrent_insert_loser_reuses_winner():
    existing = make_existing(severity=Severity.LOW)
    service, repository, pipeline = make_service(
        existing=None,
        pipeline_start=IntegrityError("INSERT", {}, Exception("duplicate")),
    )
    # First lookup (before insert) misses; second lookup (after conflict) wins.
    repository.find_active_by_fingerprint.side_effect = [None, existing]

    with patch("app.webhooks.service.MonitoringService"):
        result = service.ingest(
            CustomWebhookAdapter(),
            request(),
            IncidentSource.CUSTOM,
            tenant_id=1,
        )

    assert result == [existing]
    assert existing.occurrence_count == 2
    assert existing.severity == Severity.CRITICAL
    repository.update.assert_called_once_with(existing)
    pipeline.start.assert_called_once()

from datetime import datetime, timezone
from typing import TypeVar

from sqlalchemy.exc import IntegrityError

from app.models.enums import IncidentSource, IncidentStatus, Severity
from app.models.incident import Incident
from app.monitoring.service import MonitoringService
from app.pipelines.incident import IncidentPipeline
from app.repositories.incident import IncidentRepository
from app.webhooks.adapters.base import WebhookAdapter

T = TypeVar("T")

_SEVERITY_RANK = {
    Severity.UNKNOWN: 0,
    Severity.LOW: 1,
    Severity.MEDIUM: 2,
    Severity.HIGH: 3,
    Severity.CRITICAL: 4,
}


def _severity_rank(value: Severity | str | None) -> int:
    try:
        return _SEVERITY_RANK[Severity(value)]  # type: ignore[index]
    except (KeyError, TypeError, ValueError):
        return 0


class WebhookService:

    def __init__(
        self,
        pipeline: IncidentPipeline,
        repository: IncidentRepository,
    ) -> None:
        self.pipeline = pipeline
        self.repository = repository

    @staticmethod
    def _refresh_active_incident(
        existing: Incident,
        incoming_severity: Severity | None,
    ) -> Incident:
        """Record a repeated firing alert without creating a duplicate.

        ``occurrence_count`` and ``last_seen_at`` make repeated alerts visible;
        severity is only escalated, never silently downgraded.
        """
        existing.last_seen_at = datetime.now(timezone.utc)
        existing.occurrence_count = (existing.occurrence_count or 1) + 1
        if _severity_rank(incoming_severity) > _severity_rank(existing.severity):
            existing.severity = incoming_severity
        return existing

    def ingest(
        self,
        adapter: WebhookAdapter[T],
        request: T,
        source: IncidentSource = IncidentSource.CUSTOM,
        *,
        tenant_id: int,
    ) -> list[Incident]:

        MonitoringService.webhook_received(source)

        webhook_incidents = adapter.parse(request)

        results: list[Incident] = []

        for webhook_incident in webhook_incidents:

            incident = webhook_incident.incident
            fingerprint = incident.fingerprint

            existing = None

            if fingerprint:
                existing = self.repository.find_active_by_fingerprint(
                    fingerprint,
                    tenant_id,
                )

            # -----------------------------
            # RESOLVED ALERT
            # -----------------------------
            if webhook_incident.resolved:

                if existing is None:
                    # Ignore resolved event if there is
                    # no active incident.
                    continue

                existing.status = IncidentStatus.RESOLVED

                updated = self.repository.update(existing)

                results.append(updated)

                MonitoringService.webhook_success()

                continue

            # -----------------------------
            # FIRING ALERT
            # -----------------------------
            if existing is not None:
                self._refresh_active_incident(existing, incident.severity)
                results.append(self.repository.update(existing))
                MonitoringService.webhook_success()
                continue

            try:
                created = self.pipeline.start(
                    incident,
                    tenant_id=tenant_id,
                )
            except IntegrityError:
                # Concurrent alerts can both pass the lookup above. The
                # partial unique index lets exactly one INSERT win; the
                # loser reuses and refreshes the existing incident.
                existing = (
                    self.repository.find_active_by_fingerprint(
                        fingerprint,
                        tenant_id,
                    )
                    if fingerprint
                    else None
                )
                if existing is None:
                    MonitoringService.webhook_failed(source)
                    MonitoringService.webhook_failure()
                    raise

                self._refresh_active_incident(existing, incident.severity)
                results.append(self.repository.update(existing))
                MonitoringService.webhook_success()
                continue
            except Exception:
                MonitoringService.webhook_failed(source)
                MonitoringService.webhook_failure()
                raise

            results.append(created)
            MonitoringService.webhook_success()

        return results

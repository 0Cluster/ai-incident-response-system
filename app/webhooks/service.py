from datetime import datetime, timezone
from typing import TypeVar

from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError

from app.models.enums import (
    IncidentSource,
    IncidentStatus,
    RemoteAgentStatus,
    Severity,
)
from app.models.incident import Incident
from app.models.remote_agent import RemoteAgent
from app.monitoring.service import MonitoringService
from app.pipelines.incident import IncidentPipeline
from app.repositories.incident import IncidentRepository
from app.schemas.incident import IncidentCreate
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

    def _resolve_target_agent(
        self,
        tenant_id: int,
        reference: str | None,
    ) -> RemoteAgent | None:
        """Resolve an alert label to a registered agent in the same tenant.

        Grafana commonly supplies ``instance="host:9100"``. We accept the full
        value, the hostname without the port, the agent key, or the display
        name. Unknown targets are left unassigned rather than routing an alert
        to a different server.
        """
        if reference is None:
            return None
        value = reference.strip()
        if not value:
            return None

        candidates = [value]
        if ":" in value:
            candidates.append(value.rsplit(":", 1)[0])

        filters = [
            RemoteAgent.tenant_id == tenant_id,
            RemoteAgent.status == RemoteAgentStatus.ACTIVE,
            or_(
                RemoteAgent.agent_key.in_(candidates),
                RemoteAgent.hostname.in_(candidates),
                RemoteAgent.display_name.in_(candidates),
            ),
        ]
        agent = self.repository.db.query(RemoteAgent).filter(*filters).first()
        if agent is not None:
            return agent

        # Internal/API callers may use a numeric target id as a convenience.
        if value.isdigit():
            return (
                self.repository.db.query(RemoteAgent)
                .filter(
                    RemoteAgent.id == int(value),
                    RemoteAgent.tenant_id == tenant_id,
                    RemoteAgent.status == RemoteAgentStatus.ACTIVE,
                )
                .first()
            )
        return None

    def _with_target_agent(
        self,
        incident,
        tenant_id: int,
    ) -> IncidentCreate:
        """Return incident data with a resolved target agent id."""
        if incident.target_agent_id is not None:
            return incident
        agent = self._resolve_target_agent(
            tenant_id,
            incident.target_agent_ref,
        )
        if agent is None:
            return incident
        return incident.model_copy(update={"target_agent_id": agent.id})

    @staticmethod
    def _refresh_active_incident(
        existing: Incident,
        incoming_severity: Severity | None,
        target_agent_id: int | None = None,
    ) -> Incident:
        """Record a repeated firing alert without creating a duplicate.

        ``occurrence_count`` and ``last_seen_at`` make repeated alerts visible;
        severity is only escalated, never silently downgraded. A newly supplied
        target agent fills an unassigned incident but never silently retargets
        an already-assigned one.
        """
        existing.last_seen_at = datetime.now(timezone.utc)
        existing.occurrence_count = (existing.occurrence_count or 1) + 1
        if _severity_rank(incoming_severity) > _severity_rank(existing.severity):
            existing.severity = incoming_severity
        if existing.target_agent_id is None and target_agent_id is not None:
            existing.target_agent_id = target_agent_id
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

            incident = self._with_target_agent(
                webhook_incident.incident,
                tenant_id,
            )
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
                self._refresh_active_incident(
                    existing,
                    incident.severity,
                    incident.target_agent_id,
                )
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

                self._refresh_active_incident(
                    existing,
                    incident.severity,
                    incident.target_agent_id,
                )
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

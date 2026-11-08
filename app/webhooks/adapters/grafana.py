from typing import override

from app.models.enums import (
    IncidentSource,
    Severity,
)
from app.schemas.incident import IncidentCreate
from app.webhooks.models import WebhookIncident
from app.webhooks.schemas import GrafanaWebhookRequest

from .base import WebhookAdapter


class GrafanaWebhookAdapter(
    WebhookAdapter[GrafanaWebhookRequest],
):

    _SEVERITY_ALIASES = {
        "warn": Severity.HIGH,
        "warning": Severity.HIGH,
        "error": Severity.HIGH,
        "info": Severity.LOW,
        "critical": Severity.CRITICAL,
        "high": Severity.HIGH,
        "medium": Severity.MEDIUM,
        "low": Severity.LOW,
    }

    @override
    def parse(
        self,
        request: GrafanaWebhookRequest,
    ) -> list[WebhookIncident]:

        incidents: list[WebhookIncident] = []

        for alert in request.alerts:

            severity = Severity.HIGH
            raw = (alert.labels.severity or "").lower()

            if raw:
                try:
                    severity = Severity(raw.upper())
                except ValueError:
                    severity = self._SEVERITY_ALIASES.get(raw, Severity.HIGH)

            elif alert.status.lower() == "firing":
                severity = Severity.CRITICAL

            message = (
                request.message
                or alert.annotations.summary
                or alert.annotations.description
                or f"{alert.labels.alertname} on {alert.labels.instance or 'unknown'}"
            )
            title = alert.labels.alertname
            if alert.labels.instance:
                title = f"{title} on {alert.labels.instance}"

            incidents.append(
                WebhookIncident(
                    incident=IncidentCreate(
                        title=title,
                        message=message,
                        severity=severity,
                        source=IncidentSource.GRAFANA,
                        fingerprint=alert.fingerprint or None,
                        target_agent_ref=(
                            alert.labels.agent_id
                            or alert.labels.agent
                            or alert.labels.instance
                        ),
                    ),
                    resolved=(
                        alert.status.lower()
                        == "resolved"
                    ),
                )
            )

        return incidents

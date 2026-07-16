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

    @override
    def parse(
        self,
        request: GrafanaWebhookRequest,
    ) -> list[WebhookIncident]:

        incidents: list[WebhookIncident] = []

        for alert in request.alerts:

            severity = Severity.HIGH

            if alert.labels.severity:

                try:
                    severity = Severity(
                        alert.labels.severity.upper(),
                    )

                except ValueError:
                    pass

            elif alert.status == "firing":
                severity = Severity.CRITICAL

            incidents.append(
                WebhookIncident(
                    incident=IncidentCreate(
                        title=alert.labels.alertname,
                        message=request.message,
                        severity=severity,
                        source=IncidentSource.GRAFANA,
                        fingerprint=alert.fingerprint,
                    ),
                    resolved=(
                        alert.status.lower()
                        == "resolved"
                    ),
                )
            )

        return incidents

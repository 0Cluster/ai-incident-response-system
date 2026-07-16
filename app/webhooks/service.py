from typing import TypeVar

from app.models.enums import IncidentStatus
from app.models.incident import Incident
from app.pipelines.incident import IncidentPipeline
from app.repositories.incident import IncidentRepository
from app.webhooks.adapters.base import WebhookAdapter

T = TypeVar("T")


class WebhookService:

    def __init__(
        self,
        pipeline: IncidentPipeline,
        repository: IncidentRepository,
    ) -> None:
        self.pipeline = pipeline
        self.repository = repository

    def ingest(
        self,
        adapter: WebhookAdapter[T],
        request: T,
    ) -> list[Incident]:

        webhook_incidents = adapter.parse(request)

        results: list[Incident] = []

        for webhook_incident in webhook_incidents:

            incident = webhook_incident.incident
            fingerprint = incident.fingerprint

            existing = None

            if fingerprint:
                existing = self.repository.find_active_by_fingerprint(
                    fingerprint,
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

                continue

            # -----------------------------
            # FIRING ALERT
            # -----------------------------
            if existing is not None:
                results.append(existing)
                continue

            created = self.pipeline.start(
                incident,
            )

            results.append(created)

        return results

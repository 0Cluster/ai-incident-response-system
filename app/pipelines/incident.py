import logging

from app.monitoring.service import MonitoringService
from app.schemas.incident import IncidentCreate
from app.services.incident import IncidentService
from app.tasks.outbox import dispatch_outbox

logger = logging.getLogger(__name__)


class IncidentPipeline:

    def __init__(
        self,
        service: IncidentService,
    ):
        self.service = service

    def start(
        self,
        data: IncidentCreate,
        *,
        tenant_id: int,
    ):

        incident = self.service.create_incident(
            data,
            tenant_id=tenant_id,
        )

        MonitoringService.incident_created(
            incident.severity,
        )

        try:
            # Fast path only. The outbox row is already committed, so a
            # broker failure here is recovered by the periodic poller.
            dispatch_outbox.delay()
        except Exception:
            logger.exception(
                "Celery broker unavailable for incident %s; "
                "analysis remains queued in the outbox",
                incident.id,
            )

        return incident

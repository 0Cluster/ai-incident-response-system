from app.monitoring.service import MonitoringService
from app.schemas.incident import IncidentCreate
from app.services.incident import IncidentService
from app.tasks.incident import analyze_incident


class IncidentPipeline:

    def __init__(
        self,
        service: IncidentService,
    ):
        self.service = service

    def start(
        self,
        data: IncidentCreate,
    ):

        incident = self.service.create_incident(
            data,
        )

        MonitoringService.incident_created(
            incident.severity,
        )

        analyze_incident.delay(
            incident.id,
        )

        return incident

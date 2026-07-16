from sqlalchemy.orm import Session

from app.ai.analyzer import IncidentAnalyzer
from app.models.enums import AnalysisStatus, AutomationStatus, IncidentStatus, Severity
from app.models.incident import Incident
from app.repositories.incident import IncidentRepository
from app.schemas.incident import IncidentCreate, IncidentUpdate
from app.exceptions.incident import IncidentNotFoundError


class IncidentService:
    def __init__(
        self,
        repository: IncidentRepository,
        analyzer: IncidentAnalyzer,
    ):
        self.repository = repository
        self.analyzer = analyzer

    def create_incident(
        self,
        data: IncidentCreate,
    ) -> Incident:

        incident = Incident(
            title=data.title,
            message=data.message,
            status=IncidentStatus.OPEN,
            analysis_status=AnalysisStatus.PENDING,
            automation_status=AutomationStatus.PENDING,
            severity=data.severity,
            source = data.source,
            fingerprint=data.fingerprint,

        )

        return self.repository.create(incident)

    def get_incident(self, incident_id: int) -> Incident:
        incident = self.repository.get(incident_id)

        if incident is None:
            raise IncidentNotFoundError(incident_id)

        return incident

    def list_incidents(self) -> list[Incident]:
        return self.repository.get_all()

    def update_incident(
        self,
        incident_id: int,
        data: IncidentUpdate,
    ) -> Incident:
        incident = self.repository.get(incident_id)

        if incident is None:
            raise IncidentNotFoundError(incident_id)

        updates = data.model_dump(exclude_unset=True)

        for field, value in updates.items():
            setattr(incident, field, value)

        return self.repository.update(incident)

    def delete_incident(self, incident_id: int) -> None:
        incident = self.repository.get(incident_id)

        if incident is None:
            raise IncidentNotFoundError(incident_id)

        self.repository.delete(incident)

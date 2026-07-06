from sqlalchemy.orm import Session

from app.ai.analyzer import IncidentAnalyzer
from app.models.enums import IncidentStatus, Severity
from app.models.incident import Incident
from app.repositories.incident import IncidentRepository
from app.schemas.incident import IncidentCreate, IncidentUpdate
from app.exceptions.incident import IncidentNotFoundError


class IncidentService:
    def __init__(self, db: Session):
        self.repository = IncidentRepository(db)
        self.analyzer = IncidentAnalyzer()

    def create_incident(self, data: IncidentCreate) -> Incident:
        incident = Incident(
            title=data.title,
            message=data.message,
            status=IncidentStatus.PENDING,
        )

        incident = self.repository.create(incident)

        try:
            incident.status = IncidentStatus.PROCESSING
            self.repository.update(incident)

            analysis = self.analyzer.analyze(incident.message)

            incident.ai_summary = analysis.summary
            incident.severity = Severity(analysis.severity)
            incident.recommendation = analysis.recommendation
            incident.status = IncidentStatus.COMPLETED

            return self.repository.update(incident)

        except Exception:
            incident.status = IncidentStatus.FAILED
            self.repository.update(incident)
            raise

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

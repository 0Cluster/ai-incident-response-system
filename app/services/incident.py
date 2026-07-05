from sqlalchemy.orm import Session

from app.exceptions.incident import IncidentNotFoundError
from app.models.incident import Incident
from app.repositories.incident import IncidentRepository
from app.schemas.incident import IncidentCreate
from app.schemas.incident import IncidentUpdate


class IncidentService:
    def __init__(self, db: Session):
        self.repository = IncidentRepository(db)

    def create_incident(self, incident: IncidentCreate) -> Incident:
        db_incident = Incident(
            title=incident.title,
            message=incident.message,
        )

        return self.repository.create(db_incident)

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

    def delete_incident(
        self,
        incident_id: int,
    ) -> None:
        incident = self.repository.get(incident_id)

        if incident is None:
            raise IncidentNotFoundError(incident_id)

        self.repository.delete(incident)








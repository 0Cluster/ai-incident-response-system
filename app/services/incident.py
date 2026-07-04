from sqlalchemy.orm import Session

from app.models.incident import Incident
from app.repositories.incident import IncidentRepository


class IncidentService:
    def __init__(self, db: Session):
        self.repository = IncidentRepository(db)

    def create_incident(
        self,
        title: str,
        message: str,
    ) -> Incident:
        incident = Incident(
            title=title,
            message=message,
        )

        return self.repository.create(incident)

    def get_incident(self, incident_id: int) -> Incident | None:
        return self.repository.get(incident_id)

    def list_incidents(self) -> list[Incident]:
        return self.repository.get_all()

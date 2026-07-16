from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import IncidentStatus
from app.models.incident import Incident
from app.repositories.base import BaseRepository


class IncidentRepository(BaseRepository[Incident]):
    def __init__(self, db: Session):
        super().__init__(db, Incident)

    def find_active_by_fingerprint(
        self,
        fingerprint: str,
    ) -> Incident | None:

        return (
            self.db.query(Incident)
            .filter(
                Incident.fingerprint == fingerprint,
                Incident.status != IncidentStatus.RESOLVED,
            )
            .first()
        )

    def get_by_title(self, title: str) -> Incident | None:
        statement = select(Incident).where(Incident.title == title)
        result = self.db.execute(statement)
        return result.scalar_one_or_none()

    def get_latest(self, limit: int = 10) -> list[Incident]:
        statement = (
            select(Incident)
            .order_by(Incident.id.desc())
            .limit(limit)
        )

        result = self.db.execute(statement)
        return list(result.scalars().all())

    def search(self, keyword: str) -> list[Incident]:
        statement = select(Incident).where(
            Incident.title.ilike(f"%{keyword}%")
            | Incident.message.ilike(f"%{keyword}%")
        )

        result = self.db.execute(statement)
        return list(result.scalars().all())

    def update(self, incident: Incident) -> Incident:
        self.db.commit()
        self.db.refresh(incident)
        return incident

    def delete_by_id(self, incident_id: int) -> bool:
        incident = self.get(incident_id)

        if incident is None:
            return False

        self.db.delete(incident)
        self.db.commit()
        return True

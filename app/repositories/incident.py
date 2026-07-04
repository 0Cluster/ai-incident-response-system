from sqlalchemy.orm import Session

from app.models.incident import Incident
from app.repositories.base import BaseRepository


class IncidentRepository(BaseRepository[Incident]):
    def __init__(self, db: Session):
        super().__init__(db, Incident)

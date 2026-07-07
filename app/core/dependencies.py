from collections.abc import Generator

from fastapi import Depends
from sqlalchemy.orm import Session

from app.ai.analyzer import IncidentAnalyzer
from app.database.session import SessionLocal
from app.repositories.incident import IncidentRepository
from app.services.incident import IncidentService


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()

    try:
        yield db
    finally:
        db.close()


def get_incident_repository(
    db: Session = Depends(get_db),
) -> IncidentRepository:
    return IncidentRepository(db)


def get_incident_service(
    repository: IncidentRepository = Depends(get_incident_repository),
) -> IncidentService:
    return IncidentService(
        repository=repository,
        analyzer=IncidentAnalyzer(),
    )

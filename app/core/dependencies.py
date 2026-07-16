from collections.abc import Generator

from fastapi import Depends
from sqlalchemy.orm import Session

from app.ai.analyzer import IncidentAnalyzer
from app.database.session import SessionLocal
from app.pipelines.incident import IncidentPipeline
from app.repositories.incident import IncidentRepository
from app.services.incident import IncidentService
from app.webhooks.service import WebhookService


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
    repository: IncidentRepository = Depends(
        get_incident_repository,
    ),
) -> IncidentService:
    return IncidentService(
        repository=repository,
        analyzer=IncidentAnalyzer(),
    )


def get_incident_pipeline(
    service: IncidentService = Depends(
        get_incident_service,
    ),
) -> IncidentPipeline:

    return IncidentPipeline(
        service,
    )


def get_webhook_service(
    pipeline: IncidentPipeline = Depends(
        get_incident_pipeline,
    ),
    repository: IncidentRepository = Depends(
        get_incident_repository,
    ),
) -> WebhookService:

    return WebhookService(
        pipeline=pipeline,
        repository=repository,
    )

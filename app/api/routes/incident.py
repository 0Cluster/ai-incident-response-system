from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from app.core.dependencies import get_db, get_incident_pipeline
from app.monitoring.service import MonitoringService
from app.pipelines.incident import IncidentPipeline
from app.schemas.incident import (
    IncidentCreate,
    IncidentResponse,
    IncidentUpdate,
)
from app.services.incident import IncidentService
from app.tasks.incident import analyze_incident

router = APIRouter(
    prefix="/incidents",
    tags=["Incidents"],
)


@router.post("/", response_model=IncidentResponse)
def create_incident(
    data: IncidentCreate,
    pipeline: IncidentPipeline = Depends(
        get_incident_pipeline,
    ),
):
    return pipeline.start(data)


@router.get("/", response_model=list[IncidentResponse])
def list_incidents(
    db: Session = Depends(get_db),
):
    service = IncidentService(db)  # pyright: ignore[reportCallIssue]
    return service.list_incidents()


@router.get("/{incident_id}", response_model=IncidentResponse)
def get_incident(
    incident_id: int,
    db: Session = Depends(get_db),
):
    service = IncidentService(db)  # pyright: ignore[reportCallIssue]

    incident = service.get_incident(incident_id)

    if incident is None:
        raise HTTPException(
            status_code=404,
            detail="Incident not found",
        )

    return incident


@router.patch(
    "/{incident_id}",
    response_model=IncidentResponse,
)
def update_incident(
    incident_id: int,
    data: IncidentUpdate,
    db: Session = Depends(get_db),
):
    service = IncidentService(db)  # pyright: ignore[reportCallIssue]

    return service.update_incident(
        incident_id,
        data,
    )


@router.delete(
    "/{incident_id}",
    status_code=204,
)
def delete_incident(
    incident_id: int,
    db: Session = Depends(get_db),
):
    service = IncidentService(db)  # pyright: ignore[reportCallIssue]

    service.delete_incident(incident_id)

    return Response(status_code=204)

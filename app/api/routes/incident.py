from fastapi import APIRouter, Depends, HTTPException,Response,BackgroundTasks
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.services.incident import IncidentService
from app.schemas.incident import (
    IncidentCreate,
    IncidentResponse,
    IncidentUpdate,
)

router = APIRouter(
    prefix="/incidents",
    tags=["Incidents"],
)


@router.post(
    "/",
    response_model=IncidentResponse,
)
def create_incident(
    data: IncidentCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    service = IncidentService(db)

    incident = service.create_incident(data)

    background_tasks.add_task(
        analyze_incident,
        incident.id,
    )

    return incident


@router.get("/", response_model=list[IncidentResponse])
def list_incidents(
    db: Session = Depends(get_db),
):
    service = IncidentService(db)
    return service.list_incidents()


@router.get("/{incident_id}", response_model=IncidentResponse)
def get_incident(
    incident_id: int,
    db: Session = Depends(get_db),
):
    service = IncidentService(db)

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
    service = IncidentService(db)

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
    service = IncidentService(db)

    service.delete_incident(incident_id)

    return Response(status_code=204)

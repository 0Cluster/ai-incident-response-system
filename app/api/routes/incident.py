from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy.exc import IntegrityError

from app.core.auth import Principal, require_role
from app.core.dependencies import get_db, get_incident_pipeline, get_incident_service
from app.core.security import rate_limit
from app.models.enums import IncidentSource, IncidentStatus, Severity, UserRole
from app.pipelines.incident import IncidentPipeline
from app.schemas.automation import AutomationRunResponse
from app.schemas.incident import (
    IncidentCreate,
    IncidentResponse,
    IncidentUpdate,
    PaginatedIncidents,
)
from app.services.automation_run import AutomationRunService
from app.services.incident import IncidentService
from sqlalchemy.orm import Session

router = APIRouter(
    prefix="/incidents",
    tags=["Incidents"],
)


@router.post("/", response_model=IncidentResponse)
def create_incident(
    data: IncidentCreate,
    request: Request,
    pipeline: IncidentPipeline = Depends(
        get_incident_pipeline,
    ),
    principal: Principal = Depends(require_role(UserRole.RESPONDER)),
):
    rate_limit(request)
    try:
        return pipeline.start(data, tenant_id=principal.tenant_id)
    except IntegrityError as exc:
        raise HTTPException(
            status_code=409,
            detail=(
                "An active incident with this fingerprint already exists. "
                "Resolve/close it before creating a new one."
            ),
        ) from exc


@router.get("/", response_model=PaginatedIncidents)
def list_incidents(
    status: IncidentStatus | None = Query(default=None),
    severity: Severity | None = Query(default=None),
    source: IncidentSource | None = Query(default=None),
    q: str | None = Query(default=None, max_length=255),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    service: IncidentService = Depends(get_incident_service),
    principal: Principal = Depends(require_role(UserRole.VIEWER)),
):
    incidents, total = service.list_filtered(
        tenant_id=principal.tenant_id,
        status=status,
        severity=severity,
        source=source,
        query=q,
        limit=limit,
        offset=offset,
    )
    return PaginatedIncidents(
        items=incidents,
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/stats/summary")
def incident_stats(
    status: IncidentStatus | None = Query(default=None),
    severity: Severity | None = Query(default=None),
    source: IncidentSource | None = Query(default=None),
    q: str | None = Query(default=None, max_length=255),
    service: IncidentService = Depends(get_incident_service),
    principal: Principal = Depends(require_role(UserRole.VIEWER)),
):
    total, by_status, by_severity = service.stats(
        tenant_id=principal.tenant_id,
        status=status,
        severity=severity,
        source=source,
        query=q,
    )
    return {"total": total, "by_status": by_status, "by_severity": by_severity}


@router.get("/{incident_id}", response_model=IncidentResponse)
def get_incident(
    incident_id: int,
    service: IncidentService = Depends(get_incident_service),
    principal: Principal = Depends(require_role(UserRole.VIEWER)),
):
    return service.get_incident(incident_id, principal.tenant_id)


@router.get("/{incident_id}/runs", response_model=list[AutomationRunResponse])
def list_incident_runs(
    incident_id: int,
    service: IncidentService = Depends(get_incident_service),
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_role(UserRole.VIEWER)),
):
    # Ensure incident belongs to the caller's tenant (raises 404 otherwise)
    service.get_incident(incident_id, principal.tenant_id)
    return AutomationRunService(db).list_by_incident(
        incident_id,
        principal.tenant_id,
    )


@router.patch(
    "/{incident_id}",
    response_model=IncidentResponse,
)
def update_incident(
    incident_id: int,
    data: IncidentUpdate,
    service: IncidentService = Depends(get_incident_service),
    principal: Principal = Depends(require_role(UserRole.RESPONDER)),
):
    return service.update_incident(
        incident_id,
        data,
        principal.tenant_id,
    )


@router.delete(
    "/{incident_id}",
    status_code=204,
)
def delete_incident(
    incident_id: int,
    service: IncidentService = Depends(get_incident_service),
    principal: Principal = Depends(require_role(UserRole.RESPONDER)),
):
    service.delete_incident(incident_id, principal.tenant_id)

    return Response(status_code=204)

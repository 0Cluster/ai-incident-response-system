"""Tenant-scoped remote job inspection and exact approval endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.core.auth import Principal, require_role
from app.core.dependencies import get_db
from app.core.security import rate_limit
from app.models.enums import RemoteJobStatus, UserRole
from app.schemas.remote import (
    RemoteApprovalRequest,
    RemoteApprovalResponse,
    RemoteJobListResponse,
    RemoteJobResponse,
)
from app.services.remote_investigation import (
    RemoteInvestigationConflictError,
    RemoteInvestigationNotFoundError,
    RemoteInvestigationService,
)
from app.services.remote_job import (
    RemoteJobExpiredError,
    RemoteJobNotFoundError,
    RemoteJobService,
)

router = APIRouter(prefix="/remote-jobs", tags=["Remote Jobs"])


def get_job_service(db: Session = Depends(get_db)) -> RemoteJobService:
    return RemoteJobService(db)


def get_remote_investigation_service(
    db: Session = Depends(get_db),
) -> RemoteInvestigationService:
    return RemoteInvestigationService(db)


@router.get("", response_model=RemoteJobListResponse)
def list_jobs(
    incident_id: int | None = Query(default=None, ge=1),
    status_filter: RemoteJobStatus | None = Query(default=None, alias="status"),
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    principal: Principal = Depends(require_role(UserRole.VIEWER)),
    service: RemoteJobService = Depends(get_job_service),
):
    jobs, total = service.list_jobs(
        tenant_id=principal.tenant_id,
        incident_id=incident_id,
        status=status_filter,
        limit=limit,
        offset=offset,
    )
    return RemoteJobListResponse(
        items=[RemoteJobResponse.model_validate(job) for job in jobs],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{job_id}", response_model=RemoteJobResponse)
def get_job(
    job_id: int,
    principal: Principal = Depends(require_role(UserRole.VIEWER)),
    service: RemoteJobService = Depends(get_job_service),
):
    job = service.get_for_tenant(job_id, principal.tenant_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return RemoteJobResponse.model_validate(job)


@router.post(
    "/{job_id}/approve",
    response_model=RemoteApprovalResponse,
)
def approve_job(
    job_id: int,
    data: RemoteApprovalRequest,
    http_request: Request,
    principal: Principal = Depends(require_role(UserRole.RESPONDER)),
    service: RemoteInvestigationService = Depends(
        get_remote_investigation_service
    ),
):
    rate_limit(http_request)
    return _decide(service, job_id, principal, True, data)


@router.post(
    "/{job_id}/reject",
    response_model=RemoteApprovalResponse,
)
def reject_job(
    job_id: int,
    data: RemoteApprovalRequest,
    http_request: Request,
    principal: Principal = Depends(require_role(UserRole.RESPONDER)),
    service: RemoteInvestigationService = Depends(
        get_remote_investigation_service
    ),
):
    rate_limit(http_request)
    return _decide(service, job_id, principal, False, data)


def _decide(
    service: RemoteInvestigationService,
    job_id: int,
    principal: Principal,
    approved: bool,
    data: RemoteApprovalRequest,
) -> RemoteApprovalResponse:
    try:
        job = service.approve(
            job_id=job_id,
            principal=principal,
            approved=approved,
            reason=data.reason,
            provided_action_hash=data.action_hash,
        )
    except RemoteInvestigationNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Job not found") from exc
    except RemoteJobNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Job not found") from exc
    except RemoteJobExpiredError as exc:
        raise HTTPException(status_code=410, detail=str(exc)) from exc
    except RemoteInvestigationConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    approval = job.approval
    action_hash = approval.action_hash if approval is not None else ""
    return RemoteApprovalResponse(
        job_id=job.id,
        approved=approved,
        status=job.status.value,
        action_hash=action_hash,
        message=(
            "Remote remediation approved."
            if approved
            else "Remote remediation rejected."
        ),
    )

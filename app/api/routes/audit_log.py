from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.auth import Principal, get_current_principal, require_superadmin
from app.core.dependencies import get_db
from app.schemas.audit_log import AuditLogCreate, AuditLogEntry, AuditLogList
from app.services.audit_log import AuditLogService
from sqlalchemy.orm import Session

router = APIRouter(prefix="/audit-log", tags=["Audit Log"])


def get_audit_service(db: Session = Depends(get_db)) -> AuditLogService:
    return AuditLogService(db)


@router.post(
    "/",
    response_model=AuditLogEntry,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_superadmin)],
)
def create_audit_entry(
    data: AuditLogCreate,
    principal: Principal = Depends(get_current_principal),
    service: AuditLogService = Depends(get_audit_service),
):
    service.log(
        action=data.action,
        principal=principal,
        resource_type=data.resource_type,
        resource_id=data.resource_id,
        details=data.details,
    )
    # Return the most recent entry for this actor/action as a confirmation.
    items, _ = service.list(
        action=data.action, limit=1, offset=0
    )
    if not items:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Audit entry could not be persisted",
        )
    return items[0]


@router.get(
    "/",
    response_model=AuditLogList,
    dependencies=[Depends(require_superadmin)],
)
def list_audit_entries(
    tenant_id: int | None = Query(default=None),
    action: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    principal: Principal = Depends(get_current_principal),
    service: AuditLogService = Depends(get_audit_service),
):
    # Non-superadmins can only see their own tenant's audit log
    effective_tenant_id = tenant_id
    if not principal.is_superadmin:
        effective_tenant_id = principal.tenant_id
    items, total = service.list(
        tenant_id=effective_tenant_id,
        action=action,
        limit=limit,
        offset=offset,
    )
    return AuditLogList(
        items=[AuditLogEntry.model_validate(i) for i in items],
        total=total,
        limit=limit,
        offset=offset,
    )

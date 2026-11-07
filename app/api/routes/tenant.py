from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.auth import Principal, require_superadmin, get_current_principal
from app.core.dependencies import get_db
from app.schemas.tenant import TenantCreate, TenantCreated, TenantResponse, TenantUpdate
from app.services.tenant import TenantService

router = APIRouter(prefix="/tenants", tags=["Tenants"])


def get_tenant_service(db: Session = Depends(get_db)) -> TenantService:
    return TenantService(db)


@router.get("/me", response_model=TenantResponse)
def my_tenant(
    principal: Principal = Depends(get_current_principal),
    service: TenantService = Depends(get_tenant_service),
):
    tenant = service.get(principal.tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return tenant


@router.get(
    "/",
    response_model=list[TenantResponse],
    dependencies=[Depends(require_superadmin)],
)
def list_tenants(service: TenantService = Depends(get_tenant_service)):
    return service.list()


@router.post(
    "/",
    response_model=TenantCreated,
    status_code=201,
    dependencies=[Depends(require_superadmin)],
)
def create_tenant(
    data: TenantCreate,
    service: TenantService = Depends(get_tenant_service),
):
    try:
        tenant, webhook_secret = service.create(
            slug=data.slug,
            name=data.name,
            is_active=data.is_active,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return TenantCreated(
        id=tenant.id,
        slug=tenant.slug,
        name=tenant.name,
        is_active=tenant.is_active,
        created_at=tenant.created_at,
        updated_at=tenant.updated_at,
        webhook_secret=webhook_secret,
    )


@router.patch(
    "/{tenant_id}",
    response_model=TenantResponse,
    dependencies=[Depends(require_superadmin)],
)
def update_tenant(
    tenant_id: int,
    data: TenantUpdate,
    service: TenantService = Depends(get_tenant_service),
):
    try:
        tenant = service.update(
            tenant_id,
            name=data.name,
            is_active=data.is_active,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return tenant

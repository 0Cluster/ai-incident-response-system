from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from app.core.auth import Principal, get_current_principal, require_role
from app.core.config import settings
from app.core.dependencies import get_db
from app.core.security import rate_limit
from app.models.enums import UserRole
from app.schemas.auth import (
    LoginRequest,
    RegisterRequest,
    TokenCreate,
    TokenInfo,
    TokenResponse,
    UserCreate,
    UserResponse,
    UserUpdate,
)
from app.services.auth import AuthService
from app.services.tenant import TenantService, ensure_default_tenant

router = APIRouter(prefix="/auth", tags=["Auth"])


def get_auth_service(db: Session = Depends(get_db)) -> AuthService:
    return AuthService(db)


def get_tenant_service(db: Session = Depends(get_db)) -> TenantService:
    return TenantService(db)


@router.post("/login", response_model=TokenResponse)
def login(
    data: LoginRequest,
    request: Request,
    service: AuthService = Depends(get_auth_service),
):
    rate_limit(request, limit=10)
    user = service.authenticate(data.email, data.password)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    raw, _token, expires_at = service.issue_token(
        user,
        name="login",
    )
    return TokenResponse(
        access_token=raw,
        expires_at=expires_at,
        user=user,
    )


@router.post(
    "/register",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
)
def register(
    data: RegisterRequest,
    request: Request,
    service: AuthService = Depends(get_auth_service),
    db: Session = Depends(get_db),
):
    if not settings.ALLOW_PUBLIC_REGISTRATION:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Public registration is disabled",
        )
    rate_limit(request)

    tenant = ensure_default_tenant(db)
    first_user = service.count_users() == 0
    try:
        user = service.create_user(
            email=data.email,
            password=data.password,
            tenant_id=tenant.id,
            role=UserRole.ADMIN if first_user else UserRole.VIEWER,
            is_active=True,
            is_superadmin=first_user,
        )
    except ValueError as exc:
        detail = str(exc)
        code = (
            status.HTTP_409_CONFLICT
            if "exists" in detail
            else status.HTTP_400_BAD_REQUEST
        )
        raise HTTPException(status_code=code, detail=detail) from exc

    raw, _token, expires_at = service.issue_token(user, name="registration")
    return TokenResponse(
        access_token=raw,
        expires_at=expires_at,
        user=user,
    )


@router.get("/me")
def me(principal: Principal = Depends(get_current_principal)):
    return {
        "user_id": principal.user_id,
        "email": principal.email,
        "role": principal.role.value,
        "auth_type": principal.auth_type,
        "tenant_id": principal.tenant_id,
        "tenant_slug": principal.tenant_slug,
        "is_superadmin": principal.is_superadmin,
    }


@router.post("/tokens", response_model=TokenResponse)
def create_token(
    data: TokenCreate,
    principal: Principal = Depends(require_role(UserRole.VIEWER)),
    service: AuthService = Depends(get_auth_service),
):
    if principal.user_id is None:
        raise HTTPException(
            status_code=400,
            detail="Only user principals can create bearer tokens",
        )
    user = service.get_user(principal.user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="User no longer exists")
    raw, _token, expires_at = service.issue_token(
        user,
        name=data.name,
        expires_hours=data.expires_hours,
    )
    return TokenResponse(
        access_token=raw,
        expires_at=expires_at,
        user=user,
    )


@router.get("/tokens", response_model=list[TokenInfo])
def list_tokens(
    principal: Principal = Depends(require_role(UserRole.VIEWER)),
    service: AuthService = Depends(get_auth_service),
):
    if principal.user_id is None:
        return []
    return service.list_tokens(principal.user_id)


@router.delete("/tokens/{token_id}", status_code=204)
def revoke_token(
    token_id: int,
    principal: Principal = Depends(require_role(UserRole.VIEWER)),
    service: AuthService = Depends(get_auth_service),
):
    ok = service.revoke_token(
        token_id,
        user_id=principal.user_id,
        tenant_id=principal.tenant_id,
        is_admin=principal.role == UserRole.ADMIN,
        is_superadmin=principal.is_superadmin,
    )
    if not ok:
        raise HTTPException(status_code=404, detail="Token not found")
    return Response(status_code=204)


@router.get(
    "/users",
    response_model=list[UserResponse],
)
def list_users(
    principal: Principal = Depends(require_role(UserRole.ADMIN)),
    service: AuthService = Depends(get_auth_service),
):
    tenant_id = None if principal.is_superadmin else principal.tenant_id
    return service.list_users(tenant_id)


@router.post(
    "/users",
    response_model=UserResponse,
    status_code=201,
)
def create_user(
    data: UserCreate,
    principal: Principal = Depends(require_role(UserRole.ADMIN)),
    service: AuthService = Depends(get_auth_service),
    tenants: TenantService = Depends(get_tenant_service),
):
    target_slug = (data.tenant_slug or principal.tenant_slug).strip().lower()
    if not principal.is_superadmin and target_slug != principal.tenant_slug:
        raise HTTPException(
            status_code=403,
            detail="Tenant admins can only create users in their own tenant",
        )
    if data.is_superadmin and not principal.is_superadmin:
        raise HTTPException(
            status_code=403,
            detail="Only a superadmin can create another superadmin",
        )
    tenant = tenants.get_by_slug(target_slug)
    if tenant is None or not tenant.is_active:
        raise HTTPException(status_code=400, detail="Tenant not found or inactive")
    try:
        return service.create_user(
            email=data.email,
            password=data.password,
            tenant_id=tenant.id,
            role=data.role,
            is_active=data.is_active,
            is_superadmin=data.is_superadmin,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.patch(
    "/users/{user_id}",
    response_model=UserResponse,
)
def update_user(
    user_id: int,
    data: UserUpdate,
    principal: Principal = Depends(require_role(UserRole.ADMIN)),
    service: AuthService = Depends(get_auth_service),
):
    target = service.get_user(user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")
    if not principal.is_superadmin and target.tenant_id != principal.tenant_id:
        raise HTTPException(status_code=404, detail="User not found")
    if target.is_superadmin and not principal.is_superadmin:
        raise HTTPException(
            status_code=403,
            detail="Only a superadmin can modify a superadmin",
        )
    user = service.update_user(
        user_id,
        role=data.role,
        is_active=data.is_active,
        password=data.password,
    )
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return user

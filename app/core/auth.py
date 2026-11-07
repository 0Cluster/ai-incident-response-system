"""Password hashing, bearer-token auth, and role checks.

Authentication is optional by default (``AUTH_REQUIRED=false``) so the
open-source demo stays usable. Setting ``AUTH_REQUIRED=true`` protects every
route that declares a role dependency. The legacy ``API_KEY`` is accepted as
an ADMIN principal.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.dependencies import get_db
from app.models.enums import UserRole
from app.models.tenant import Tenant
from app.models.user import ApiToken

PBKDF2_ITERATIONS = 260_000
_PASSWORD_SCHEME = "pbkdf2_sha256"
_ROLE_RANK = {
    UserRole.VIEWER: 1,
    UserRole.RESPONDER: 2,
    UserRole.ADMIN: 3,
}


@dataclass(frozen=True)
class Principal:
    user_id: int | None
    email: str
    role: UserRole
    auth_type: str
    tenant_id: int
    tenant_slug: str
    is_superadmin: bool = False


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _unb64(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def hash_password(password: str) -> str:
    if not password:
        raise ValueError("password must not be empty")
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        PBKDF2_ITERATIONS,
    )
    return (
        f"{_PASSWORD_SCHEME}${PBKDF2_ITERATIONS}"
        f"${_b64(salt)}${_b64(digest)}"
    )


def verify_password(password: str, encoded: str) -> bool:
    try:
        scheme, iterations, salt_b64, digest_b64 = encoded.split("$")
        if scheme != _PASSWORD_SCHEME:
            return False
        salt = _unb64(salt_b64)
        expected = _unb64(digest_b64)
        actual = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt,
            int(iterations),
        )
    except (TypeError, ValueError):
        return False
    return hmac.compare_digest(actual, expected)


def hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def generate_token() -> tuple[str, str]:
    """Return (raw token shown once, sha256 hash stored at rest)."""
    raw = secrets.token_urlsafe(32)
    return raw, hash_token(raw)


def token_expiry(hours: int | None = None) -> datetime:
    ttl = settings.AUTH_TOKEN_TTL_HOURS if hours is None else hours
    return datetime.now(timezone.utc) + timedelta(hours=max(1, ttl))


def _unauthorized(detail: str = "Not authenticated") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def _is_expired(value: datetime | None) -> bool:
    if value is None:
        return False
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value <= datetime.now(timezone.utc)


def get_default_tenant(db: Session) -> Tenant:
    tenant = db.scalar(
        select(Tenant).where(Tenant.slug == settings.DEFAULT_TENANT_SLUG)
    )
    if tenant is None:
        # Self-heal after a migration if the API started before the tables
        # existed (common with `docker compose up` followed by Alembic).
        from app.services.tenant import ensure_default_tenant

        tenant = ensure_default_tenant(db)
    if not tenant.is_active:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Default tenant is inactive",
        )
    return tenant


def default_tenant_id(db: Session = Depends(get_db)) -> int:
    """FastAPI dependency for unauthenticated, default-tenant flows."""
    return get_default_tenant(db).id


def get_current_principal(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> Principal:
    expected_key = (settings.API_KEY or "").strip()

    if x_api_key is not None and expected_key:
        if hmac.compare_digest(x_api_key, expected_key):
            tenant = get_default_tenant(db)
            return Principal(
                user_id=None,
                email="api-key",
                role=UserRole.ADMIN,
                auth_type="api_key",
                tenant_id=tenant.id,
                tenant_slug=tenant.slug,
                is_superadmin=True,
            )
        raise _unauthorized("Invalid API key")

    if authorization:
        scheme, _, raw_token = authorization.partition(" ")
        raw_token = raw_token.strip()
        if scheme.lower() != "bearer" or not raw_token:
            raise _unauthorized("Invalid Authorization header")

        token = db.scalar(
            select(ApiToken).where(
                ApiToken.token_hash == hash_token(raw_token),
            )
        )
        if token is None:
            raise _unauthorized("Invalid or revoked token")
        if _is_expired(token.expires_at):
            raise _unauthorized("Token expired")
        if token.user is None or not token.user.is_active:
            raise _unauthorized("User is inactive")

        tenant = db.get(Tenant, token.user.tenant_id)
        if tenant is None or not tenant.is_active:
            raise _unauthorized("Tenant is inactive")

        token.last_used_at = datetime.now(timezone.utc)
        db.commit()
        return Principal(
            user_id=token.user.id,
            email=token.user.email,
            role=token.user.role,
            auth_type="bearer",
            tenant_id=tenant.id,
            tenant_slug=tenant.slug,
            is_superadmin=token.user.is_superadmin,
        )

    # Backward-compatible demo mode: neither AUTH_REQUIRED nor API_KEY set.
    if not settings.AUTH_REQUIRED and not expected_key:
        tenant = get_default_tenant(db)
        return Principal(
            user_id=None,
            email="anonymous",
            role=UserRole.ADMIN,
            auth_type="anonymous",
            tenant_id=tenant.id,
            tenant_slug=tenant.slug,
            is_superadmin=True,
        )

    raise _unauthorized()


def require_role(*roles: UserRole):
    if not roles:
        raise ValueError("require_role needs at least one role")
    minimum = min(_ROLE_RANK[role] for role in roles)

    def dependency(
        principal: Principal = Depends(get_current_principal),
    ) -> Principal:
        if _ROLE_RANK.get(principal.role, 0) < minimum:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient role",
            )
        return principal

    return dependency


def require_superadmin(
    principal: Principal = Depends(require_role(UserRole.ADMIN)),
) -> Principal:
    if not principal.is_superadmin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Superadmin access required",
        )
    return principal

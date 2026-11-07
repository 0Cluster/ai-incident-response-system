import hashlib
import hmac

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.dependencies import get_db
from app.models.tenant import Tenant


def verify_webhook(
    x_webhook_secret: str | None = Header(
        default=None,
        alias="X-Webhook-Secret",
    ),
    db: Session | None = None,
) -> None:
    """Verify a webhook secret against the global WEBHOOK_SECRET.

    Kept dependency-free so it can be called directly in unit tests.
    When a db session is supplied and the request includes X-Tenant-Slug
    with a tenant that has a per-tenant webhook_secret_hash, the tenant
    hash is used instead of the global secret.
    """
    expected = settings.WEBHOOK_SECRET
    if x_webhook_secret is None or not hmac.compare_digest(x_webhook_secret, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid webhook secret",
        )


def verify_webhook_for_tenant(
    x_webhook_secret: str | None = Header(
        default=None,
        alias="X-Webhook-Secret",
    ),
    x_tenant_slug: str | None = Header(
        default=None,
        alias="X-Tenant-Slug",
    ),
    db: Session = Depends(get_db),
) -> int:
    """Validate a webhook and return the tenant that owns the incident.

    A supplied ``X-Tenant-Slug`` is authoritative: it must resolve to a
    known tenant. Tenants created through the tenant API have a
    ``webhook_secret_hash`` and must present that tenant's secret. The
    default tenant is the only legacy tenant allowed to use the global
    ``WEBHOOK_SECRET`` with an explicit slug.

    Omitting ``X-Tenant-Slug`` preserves the original single-tenant
    behaviour: the global secret targets the default tenant.
    """
    if x_tenant_slug is not None:
        normalized_slug = x_tenant_slug.strip().lower()
        if not normalized_slug:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid webhook secret or tenant slug",
            )

        tenant = db.scalar(
            select(Tenant).where(Tenant.slug == normalized_slug)
        )
        if tenant is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid webhook secret or tenant slug",
            )

        if tenant.webhook_secret_hash is not None:
            incoming_hash = hashlib.sha256(
                (x_webhook_secret or "").encode("utf-8")
            ).hexdigest()
            if not hmac.compare_digest(
                incoming_hash,
                tenant.webhook_secret_hash,
            ):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid webhook secret",
                )
            if not tenant.is_active:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Tenant is inactive",
                )
            return tenant.id

        # Legacy tenant without a per-tenant secret. Never let the global
        # secret address an arbitrary tenant; only the default tenant may
        # be selected explicitly this way.
        if tenant.slug != settings.DEFAULT_TENANT_SLUG:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Tenant has no webhook secret configured",
            )
        if not tenant.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Tenant is inactive",
            )

    expected = settings.WEBHOOK_SECRET
    if x_webhook_secret is None or not hmac.compare_digest(
        x_webhook_secret, expected
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid webhook secret",
        )

    from app.core.auth import get_default_tenant

    return get_default_tenant(db).id

from __future__ import annotations

import hashlib
import re
import secrets

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.tenant import Tenant
from app.services.automation_rule import seed_default_rules

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,99}$")


def ensure_default_tenant(db: Session) -> Tenant:
    """Create the bootstrap tenant (and its baseline rules) if missing.

    The zero-config demo relies on a tenant with slug ``default``.  Running
    this at application startup keeps fresh databases usable after
    ``alembic upgrade head`` without an extra manual seed step.
    """
    tenant = db.scalar(
        select(Tenant).where(Tenant.slug == settings.DEFAULT_TENANT_SLUG)
    )
    created = tenant is None
    if tenant is None:
        tenant = Tenant(
            slug=settings.DEFAULT_TENANT_SLUG,
            name=settings.DEFAULT_TENANT_NAME,
            is_active=True,
        )
        db.add(tenant)
        db.flush()

    if created:
        seed_default_rules(db, tenant.id)

    db.commit()
    db.refresh(tenant)
    return tenant


def _webhook_secret() -> tuple[str, str]:
    raw = secrets.token_urlsafe(32)
    return raw, hashlib.sha256(raw.encode("utf-8")).hexdigest()


class TenantService:
    def __init__(self, db: Session):
        self.db = db

    def get(self, tenant_id: int) -> Tenant | None:
        return self.db.get(Tenant, tenant_id)

    def get_by_slug(self, slug: str) -> Tenant | None:
        return self.db.scalar(
            select(Tenant).where(Tenant.slug == slug.strip().lower())
        )

    def list(self) -> list[Tenant]:
        return list(self.db.scalars(select(Tenant).order_by(Tenant.id)).all())

    def create(
        self,
        *,
        slug: str,
        name: str,
        is_active: bool = True,
    ) -> tuple[Tenant, str]:
        normalized = slug.strip().lower()
        if not _SLUG_RE.fullmatch(normalized):
            raise ValueError(
                "slug must match [a-z0-9][a-z0-9-]{1,99}, e.g. 'acme'"
            )
        clean_name = name.strip()
        if not clean_name:
            raise ValueError("name must not be empty")
        if self.get_by_slug(normalized) is not None:
            raise ValueError("tenant slug already exists")

        raw_secret, secret_hash = _webhook_secret()
        tenant = Tenant(
            slug=normalized,
            name=clean_name[:255],
            is_active=is_active,
            webhook_secret_hash=secret_hash,
        )
        try:
            self.db.add(tenant)
            self.db.flush()
            seed_default_rules(self.db, tenant.id)
            self.db.commit()
            self.db.refresh(tenant)
            return tenant, raw_secret
        except Exception:
            self.db.rollback()
            raise

    def update(
        self,
        tenant_id: int,
        *,
        name: str | None = None,
        is_active: bool | None = None,
    ) -> Tenant | None:
        tenant = self.get(tenant_id)
        if tenant is None:
            return None
        if name is not None:
            clean_name = name.strip()
            if not clean_name:
                raise ValueError("name must not be empty")
            tenant.name = clean_name[:255]
        if is_active is not None:
            if not is_active and tenant.slug == settings.DEFAULT_TENANT_SLUG:
                raise ValueError("the default tenant cannot be deactivated")
            tenant.is_active = is_active
        self.db.commit()
        self.db.refresh(tenant)
        return tenant

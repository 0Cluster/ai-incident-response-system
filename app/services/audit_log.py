from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import Principal
from app.models.audit_log import AuditLog


class AuditLogService:
    """Append-only audit log. Writes are best-effort and never fail a
    request if the audit record cannot be persisted.
    """

    def __init__(self, db: Session):
        self.db = db

    def log(
        self,
        *,
        action: str,
        principal: Principal | None = None,
        resource_type: str | None = None,
        resource_id: str | None = None,
        tenant_id: int | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        try:
            actor_user_id = None
            actor_email = None
            actor_is_superadmin = False
            if principal is not None:
                actor_user_id = principal.user_id
                actor_email = principal.email
                actor_is_superadmin = principal.is_superadmin
            if tenant_id is None and principal is not None:
                tenant_id = principal.tenant_id

            entry = AuditLog(
                actor_user_id=actor_user_id,
                actor_email=actor_email,
                actor_is_superadmin=actor_is_superadmin,
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                tenant_id=tenant_id,
                details=details,
            )
            self.db.add(entry)
            self.db.commit()
        except Exception:
            self.db.rollback()

    def list(
        self,
        *,
        tenant_id: int | None = None,
        action: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[AuditLog], int]:
        statement = select(AuditLog).order_by(AuditLog.created_at.desc())
        count_statement = select(AuditLog.id)
        if tenant_id is not None:
            statement = statement.where(AuditLog.tenant_id == tenant_id)
            count_statement = count_statement.where(AuditLog.tenant_id == tenant_id)
        if action is not None:
            statement = statement.where(AuditLog.action == action)
            count_statement = count_statement.where(AuditLog.action == action)
        total = len(self.db.scalars(count_statement).all())
        statement = statement.limit(limit).offset(offset)
        items = list(self.db.scalars(statement).all())
        return items, total

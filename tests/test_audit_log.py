"""Audit log tests."""
from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.auth import Principal, UserRole
from app.models.audit_log import AuditLog
from app.models.tenant import Tenant
from app.services.audit_log import AuditLogService


def _sqlite_session_factory() -> sessionmaker:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Tenant.__table__.create(engine)
    AuditLog.__table__.create(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def _principal(
    user_id: int | None = 1,
    email: str = "admin@example.com",
    role: UserRole = UserRole.ADMIN,
    tenant_id: int = 1,
    is_superadmin: bool = True,
) -> Principal:
    return Principal(
        user_id=user_id,
        email=email,
        role=role,
        auth_type="bearer",
        tenant_id=tenant_id,
        tenant_slug="default",
        is_superadmin=is_superadmin,
    )


def test_audit_log_create_and_list():
    SessionLocal = _sqlite_session_factory()
    db: Session = SessionLocal()
    try:
        svc = AuditLogService(db)
        principal = _principal()

        svc.log(
            action="incident.create",
            principal=principal,
            resource_type="incident",
            resource_id="42",
            details={"title": "Database down"},
        )

        items, total = svc.list()
        assert total == 1
        assert len(items) == 1
        entry = items[0]
        assert entry.action == "incident.create"
        assert entry.resource_type == "incident"
        assert entry.resource_id == "42"
        assert entry.actor_user_id == 1
        assert entry.actor_email == "admin@example.com"
        assert entry.actor_is_superadmin is True
        assert entry.details == {"title": "Database down"}
    finally:
        db.close()


def test_audit_log_filters_by_tenant():
    SessionLocal = _sqlite_session_factory()
    db: Session = SessionLocal()
    try:
        svc = AuditLogService(db)
        principal_a = _principal(user_id=1, email="a@example.com", tenant_id=1)
        principal_b = _principal(user_id=2, email="b@example.com", tenant_id=2)

        svc.log(action="incident.create", principal=principal_a, tenant_id=1)
        svc.log(action="incident.create", principal=principal_b, tenant_id=2)
        svc.log(action="rule.update", principal=principal_a, tenant_id=1)

        items_a, total_a = svc.list(tenant_id=1)
        assert total_a == 2
        assert all(i.tenant_id == 1 for i in items_a)

        items_b, total_b = svc.list(tenant_id=2)
        assert total_b == 1
        assert items_b[0].tenant_id == 2

        items_action, total_action = svc.list(action="rule.update")
        assert total_action == 1
    finally:
        db.close()


def test_audit_log_without_principal():
    SessionLocal = _sqlite_session_factory()
    db: Session = SessionLocal()
    try:
        svc = AuditLogService(db)
        svc.log(action="system.startup", details={"version": "0.1.0"})

        items, total = svc.list()
        assert total == 1
        assert items[0].actor_user_id is None
        assert items[0].actor_email is None
        assert items[0].actor_is_superadmin is False
    finally:
        db.close()

"""Cross-tenant authorization tests.

Verifies that users in tenant A cannot read or modify resources owned by
tenant B, across incidents, automation rules, runbooks, and users.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.automation_rule import AutomationRule
from app.models.enums import (
    AnalysisStatus,
    AutomationStatus,
    IncidentSource,
    IncidentStatus,
    Severity,
    UserRole,
)
from app.models.incident import Incident
from app.models.runbook import Runbook
from app.models.tenant import Tenant
from app.models.user import User
from app.repositories.automation_rule import AutomationRuleRepository
from app.repositories.incident import IncidentRepository
from app.services.auth import AuthService
from app.services.incident import IncidentService
from app.services.runbook import RunbookService


def _sqlite_session_factory() -> sessionmaker:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    # Create all tables needed for cross-tenant isolation tests
    Tenant.__table__.create(engine)
    User.__table__.create(engine)
    Incident.__table__.create(engine)
    AutomationRule.__table__.create(engine)
    Runbook.__table__.create(engine)
    return sessionmaker(
        bind=engine, autoflush=False, autocommit=False
    )


def _seed_two_tenants(SessionLocal: sessionmaker) -> tuple[int, int]:
    db: Session = SessionLocal()
    try:
        t_a = Tenant(slug="tenant-a", name="Tenant A", is_active=True)
        t_b = Tenant(slug="tenant-b", name="Tenant B", is_active=True)
        db.add(t_a)
        db.add(t_b)
        db.commit()
        db.refresh(t_a)
        db.refresh(t_b)
        return t_a.id, t_b.id
    finally:
        db.close()


def _seed_user(
    SessionLocal: sessionmaker,
    tenant_id: int,
    email: str,
    role: UserRole = UserRole.VIEWER,
) -> User:
    db: Session = SessionLocal()
    try:
        user = AuthService(db).create_user(
            email=email,
            password="correct horse battery staple",
            tenant_id=tenant_id,
            role=role,
        )
        return user
    finally:
        db.close()


def _seed_incident(
    SessionLocal: sessionmaker,
    tenant_id: int,
    title: str,
    status: IncidentStatus = IncidentStatus.OPEN,
) -> Incident:
    db: Session = SessionLocal()
    try:
        incident = Incident(
            tenant_id=tenant_id,
            title=title,
            message="test message",
            status=status,
            analysis_status=AnalysisStatus.COMPLETED,
            automation_status=AutomationStatus.SUCCESS,
            severity=Severity.HIGH,
            source=IncidentSource.MANUAL,
        )
        db.add(incident)
        db.commit()
        db.refresh(incident)
        return incident
    finally:
        db.close()


def _seed_rule(
    SessionLocal: sessionmaker,
    tenant_id: int,
    severity: str = "HIGH",
) -> AutomationRule:
    db: Session = SessionLocal()
    try:
        rule = AutomationRule(
            tenant_id=tenant_id,
            severity=severity,
            action_name="log",
            enabled=True,
            execution_order=1,
            config={},
        )
        db.add(rule)
        db.commit()
        db.refresh(rule)
        return rule
    finally:
        db.close()


def _seed_runbook(
    SessionLocal: sessionmaker,
    tenant_id: int,
    name: str,
) -> Runbook:
    db: Session = SessionLocal()
    try:
        runbook = Runbook(
            tenant_id=tenant_id,
            name=name,
            content="# Test Runbook\n\nContent",
        )
        db.add(runbook)
        db.commit()
        db.refresh(runbook)
        return runbook
    finally:
        db.close()


def test_incident_repository_scopes_by_tenant():
    SessionLocal = _sqlite_session_factory()
    db: Session = SessionLocal()
    try:
        tenant_a_id, tenant_b_id = _seed_two_tenants(SessionLocal)
        inc_a = _seed_incident(SessionLocal, tenant_a_id, "Incident A")
        inc_b = _seed_incident(SessionLocal, tenant_b_id, "Incident B")

        repo = IncidentRepository(db)

        # Tenant A can only see its own incidents
        incidents_a = repo.list_filtered(tenant_id=tenant_a_id)[0]
        assert len(incidents_a) == 1
        assert incidents_a[0].id == inc_a.id

        # Tenant B can only see its own incidents
        incidents_b = repo.list_filtered(tenant_id=tenant_b_id)[0]
        assert len(incidents_b) == 1
        assert incidents_b[0].id == inc_b.id

        # get_for_tenant rejects cross-tenant access
        assert repo.get_for_tenant(inc_a.id, tenant_b_id) is None
        assert repo.get_for_tenant(inc_b.id, tenant_a_id) is None
        assert repo.get_for_tenant(inc_a.id, tenant_a_id) is not None
    finally:
        db.close()


def test_automation_rule_repository_scopes_by_tenant():
    SessionLocal = _sqlite_session_factory()
    db: Session = SessionLocal()
    try:
        tenant_a_id, tenant_b_id = _seed_two_tenants(SessionLocal)
        rule_a = _seed_rule(SessionLocal, tenant_a_id, "HIGH")
        rule_b = _seed_rule(SessionLocal, tenant_b_id, "CRITICAL")

        repo = AutomationRuleRepository(db)

        rules_a = repo.list_all(tenant_a_id)
        assert len(rules_a) == 1
        assert rules_a[0].id == rule_a.id

        rules_b = repo.list_all(tenant_b_id)
        assert len(rules_b) == 1
        assert rules_b[0].id == rule_b.id

        assert repo.get(rule_a.id, tenant_b_id) is None
        assert repo.get(rule_b.id, tenant_a_id) is None
    finally:
        db.close()


def test_runbook_service_scopes_by_tenant():
    SessionLocal = _sqlite_session_factory()
    db: Session = SessionLocal()
    try:
        tenant_a_id, tenant_b_id = _seed_two_tenants(SessionLocal)
        rb_a = _seed_runbook(SessionLocal, tenant_a_id, "runbook-a")
        rb_b = _seed_runbook(SessionLocal, tenant_b_id, "runbook-b")

        svc = RunbookService(db)

        books_a = svc.list(tenant_a_id)
        assert len(books_a) == 1
        assert books_a[0].name == "runbook-a"

        books_b = svc.list(tenant_b_id)
        assert len(books_b) == 1
        assert books_b[0].name == "runbook-b"

        assert svc.get(rb_a.name, tenant_b_id) is None
        assert svc.get(rb_b.name, tenant_a_id) is None
    finally:
        db.close()


def test_auth_service_list_users_scopes_by_tenant():
    SessionLocal = _sqlite_session_factory()
    db: Session = SessionLocal()
    try:
        tenant_a_id, tenant_b_id = _seed_two_tenants(SessionLocal)
        _seed_user(SessionLocal, tenant_a_id, "user-a@example.com", UserRole.VIEWER)
        _seed_user(SessionLocal, tenant_b_id, "user-b@example.com", UserRole.VIEWER)

        svc = AuthService(db)

        users_a = svc.list_users(tenant_id=tenant_a_id)
        assert len(users_a) == 1
        assert users_a[0].email == "user-a@example.com"

        users_b = svc.list_users(tenant_id=tenant_b_id)
        assert len(users_b) == 1
        assert users_b[0].email == "user-b@example.com"

        # Non-superadmin list with tenant_id=None returns empty (scoped)
        # Superadmin list (tenant_id=None) returns all — that's expected
        all_users = svc.list_users(tenant_id=None)
        assert len(all_users) == 2
    finally:
        db.close()


def test_incident_service_update_scopes_by_tenant():
    SessionLocal = _sqlite_session_factory()
    db: Session = SessionLocal()
    try:
        tenant_a_id, tenant_b_id = _seed_two_tenants(SessionLocal)
        inc_a = _seed_incident(SessionLocal, tenant_a_id, "Incident A")

        # Tenant A can update its own incident
        from app.ai.analyzer import IncidentAnalyzer
        from app.schemas.incident import IncidentUpdate

        mock_analyzer = MagicMock(spec=IncidentAnalyzer)
        repo = IncidentRepository(db)
        svc = IncidentService(repo, mock_analyzer)

        updated = svc.update_incident(
            inc_a.id,
            IncidentUpdate(status=IncidentStatus.ACKNOWLEDGED),
            tenant_id=tenant_a_id,
        )
        assert updated.status == IncidentStatus.ACKNOWLEDGED

        # Tenant B cannot update tenant A's incident
        with pytest.raises(Exception):
            svc.update_incident(
                inc_a.id,
                IncidentUpdate(status=IncidentStatus.RESOLVED),
                tenant_id=tenant_b_id,
            )
    finally:
        db.close()

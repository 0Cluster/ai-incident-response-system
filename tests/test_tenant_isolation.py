"""Cross-tenant isolation tests for API and execution paths.

These tests deliberately use real bearer principals rather than the
anonymous demo principal. They cover both the HTTP boundary and the
service/engine paths that could leak another tenant's data.
"""
from __future__ import annotations

import hashlib
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.core.auth as auth
import app.core.dependencies as deps
from app.agent.state import InvestigationState
from app.automation.engine import AutomationEngine
from app.core.config import settings
from app.main import app
from app.models.audit_log import AuditLog
from app.models.automation_rule import AutomationRule
from app.models.automation_run import AutomationRun
from app.models.enums import (
    AnalysisStatus,
    AutomationStatus,
    IncidentSource,
    IncidentStatus,
    Severity,
    UserRole,
)
from app.models.incident import Incident
from app.models.outbox import OutboxEvent
from app.models.runbook import Runbook
from app.models.tenant import Tenant
from app.models.user import ApiToken, User
from app.models.workflow_state import WorkflowState
from app.services.auth import AuthService


def _hash_secret(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _seed_incident(
    db: Session,
    tenant_id: int,
    *,
    title: str = "Database down",
    severity: Severity = Severity.HIGH,
) -> Incident:
    incident = Incident(
        tenant_id=tenant_id,
        title=title,
        message="primary database unavailable",
        status=IncidentStatus.OPEN,
        analysis_status=AnalysisStatus.COMPLETED,
        automation_status=AutomationStatus.SUCCESS,
        severity=severity,
        source=IncidentSource.MANUAL,
    )
    db.add(incident)
    db.commit()
    db.refresh(incident)
    return incident


def _seed_state(
    db: Session,
    incident_id: int,
    tenant_id: int,
    *,
    status: str = "waiting_for_approval",
) -> WorkflowState:
    state = InvestigationState(
        incident_id=incident_id,
        tenant_id=tenant_id,
        actor_user_id=None,
        actor_email="seed@example.com",
        incident_title="Seeded incident",
        incident_severity="HIGH",
        workflow_status=status,
        current_step="wait_for_approval",
        requires_approval=True,
    )
    row = WorkflowState(
        incident_id=incident_id,
        tenant_id=tenant_id,
        state_json=state.model_dump(),
        status=status,
        current_step=state.current_step,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@pytest.fixture()
def tenant_env(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    for table in (
        Tenant,
        User,
        ApiToken,
        Incident,
        AutomationRule,
        AutomationRun,
        Runbook,
        WorkflowState,
        AuditLog,
        OutboxEvent,
    ):
        table.__table__.create(engine)

    SessionLocal = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
    )
    db: Session = SessionLocal()

    tenants = {
        "default": Tenant(slug="default", name="Default", is_active=True),
        "a": Tenant(
            slug="tenant-a",
            name="Tenant A",
            is_active=True,
            webhook_secret_hash=_hash_secret("secret-a"),
        ),
        "b": Tenant(
            slug="tenant-b",
            name="Tenant B",
            is_active=True,
            webhook_secret_hash=_hash_secret("secret-b"),
        ),
        "inactive": Tenant(
            slug="tenant-inactive",
            name="Inactive",
            is_active=False,
            webhook_secret_hash=_hash_secret("secret-inactive"),
        ),
    }
    for tenant in tenants.values():
        db.add(tenant)
    db.commit()
    for tenant in tenants.values():
        db.refresh(tenant)

    users = {
        "a": User(
            email="admin-a@example.com",
            tenant_id=tenants["a"].id,
            password_hash="hash",
            role=UserRole.ADMIN,
            is_active=True,
            is_superadmin=False,
        ),
        "b": User(
            email="admin-b@example.com",
            tenant_id=tenants["b"].id,
            password_hash="hash",
            role=UserRole.ADMIN,
            is_active=True,
            is_superadmin=False,
        ),
        "super": User(
            email="super@example.com",
            tenant_id=tenants["default"].id,
            password_hash="hash",
            role=UserRole.ADMIN,
            is_active=True,
            is_superadmin=True,
        ),
    }
    for user in users.values():
        db.add(user)
    db.commit()
    for user in users.values():
        db.refresh(user)

    service = AuthService(db)
    tokens = {
        key: service.issue_token(user)[0]
        for key, user in users.items()
    }

    def override_get_db():
        yield db

    monkeypatch.setattr(auth.settings, "AUTH_REQUIRED", True)
    monkeypatch.setattr(auth.settings, "API_KEY", "")
    monkeypatch.setattr(deps, "get_incident_analyzer", lambda: MagicMock())

    app.dependency_overrides[deps.get_db] = override_get_db
    try:
        with (
            patch("app.pipelines.incident.dispatch_outbox.delay") as dispatch,
            patch(
                "app.api.routes.investigation.run_investigation.delay"
            ) as run_investigation,
        ):
            yield SimpleNamespace(
                client=TestClient(app),
                db=db,
                SessionLocal=SessionLocal,
                tenants=tenants,
                users=users,
                tokens=tokens,
                dispatch=dispatch,
                run_investigation=run_investigation,
            )
    finally:
        app.dependency_overrides.clear()
        db.close()
        engine.dispose()


def test_incident_reads_and_writes_are_tenant_scoped(tenant_env):
    env = tenant_env
    incident_b = _seed_incident(env.db, env.tenants["b"].id, title="B only")

    response = env.client.get(
        f"/api/v1/incidents/{incident_b.id}",
        headers=_auth(env.tokens["a"]),
    )
    assert response.status_code == 404

    response = env.client.patch(
        f"/api/v1/incidents/{incident_b.id}",
        headers=_auth(env.tokens["a"]),
        json={"status": "RESOLVED"},
    )
    assert response.status_code == 404

    response = env.client.delete(
        f"/api/v1/incidents/{incident_b.id}",
        headers=_auth(env.tokens["a"]),
    )
    assert response.status_code == 404

    env.db.expire_all()
    still_there = env.db.get(Incident, incident_b.id)
    assert still_there is not None
    assert still_there.tenant_id == env.tenants["b"].id

    response = env.client.get(
        "/api/v1/incidents/",
        headers=_auth(env.tokens["a"]),
    )
    assert response.status_code == 200
    assert response.json()["items"] == []

    response = env.client.get(
        f"/api/v1/incidents/{incident_b.id}",
        headers=_auth(env.tokens["b"]),
    )
    assert response.status_code == 200


def test_investigation_access_requires_same_tenant_or_superadmin(tenant_env):
    env = tenant_env
    incident_a = _seed_incident(env.db, env.tenants["a"].id, title="A incident")
    incident_b = _seed_incident(env.db, env.tenants["b"].id, title="B incident")
    _seed_state(env.db, incident_a.id, env.tenants["a"].id)
    _seed_state(env.db, incident_b.id, env.tenants["b"].id)

    # Cross-tenant read is explicitly denied.
    response = env.client.get(
        f"/api/v1/investigations/{incident_b.id}",
        headers=_auth(env.tokens["a"]),
    )
    assert response.status_code == 403

    # Cross-tenant start resolves the incident through the tenant-scoped
    # repository, so it must not expose whether the incident exists.
    env.run_investigation.reset_mock()
    response = env.client.post(
        f"/api/v1/investigations/{incident_b.id}/start",
        headers=_auth(env.tokens["a"]),
    )
    assert response.status_code == 404
    env.run_investigation.assert_not_called()

    # Cross-tenant approval is denied and must not dispatch work.
    env.run_investigation.reset_mock()
    response = env.client.post(
        f"/api/v1/investigations/{incident_b.id}/approve",
        headers=_auth(env.tokens["a"]),
        json={"approved": True, "reason": "cross-tenant attempt"},
    )
    assert response.status_code == 403
    env.run_investigation.assert_not_called()

    response = env.client.get(
        "/api/v1/investigations",
        headers=_auth(env.tokens["a"]),
    )
    assert response.status_code == 200
    assert [row["incident_id"] for row in response.json()] == [incident_a.id]

    response = env.client.get(
        f"/api/v1/investigations/{incident_b.id}",
        headers=_auth(env.tokens["super"]),
    )
    assert response.status_code == 200
    assert response.json()["tenant_id"] == env.tenants["b"].id


def test_runbook_names_are_scoped_per_tenant(tenant_env):
    env = tenant_env
    env.db.add_all(
        [
            Runbook(
                tenant_id=env.tenants["a"].id,
                name="shared",
                content="tenant A runbook",
            ),
            Runbook(
                tenant_id=env.tenants["b"].id,
                name="shared",
                content="tenant B secret runbook",
            ),
            Runbook(
                tenant_id=env.tenants["b"].id,
                name="b-only",
                content="tenant B only",
            ),
        ]
    )
    env.db.commit()

    response = env.client.get(
        "/api/v1/runbooks/shared",
        headers=_auth(env.tokens["a"]),
    )
    assert response.status_code == 200
    assert response.json()["content"] == "tenant A runbook"

    response = env.client.get(
        "/api/v1/runbooks/shared",
        headers=_auth(env.tokens["b"]),
    )
    assert response.status_code == 200
    assert response.json()["content"] == "tenant B secret runbook"

    response = env.client.get(
        "/api/v1/runbooks/b-only",
        headers=_auth(env.tokens["a"]),
    )
    assert response.status_code == 404

    response = env.client.delete(
        "/api/v1/runbooks/b-only",
        headers=_auth(env.tokens["a"]),
    )
    assert response.status_code == 404

    response = env.client.get(
        "/api/v1/runbooks/",
        headers=_auth(env.tokens["a"]),
    )
    assert response.status_code == 200
    assert [item["name"] for item in response.json()["items"]] == ["shared"]

    env.db.expire_all()
    assert env.db.query(Runbook).filter(Runbook.name == "b-only").one() is not None


def test_automation_rules_and_engine_are_tenant_scoped(tenant_env):
    env = tenant_env
    rule_a = AutomationRule(
        tenant_id=env.tenants["a"].id,
        severity="HIGH",
        action_name="log",
        enabled=True,
        execution_order=1,
        config={},
    )
    rule_b = AutomationRule(
        tenant_id=env.tenants["b"].id,
        severity="HIGH",
        action_name="log",
        enabled=True,
        execution_order=1,
        config={},
    )
    env.db.add_all([rule_a, rule_b])
    env.db.commit()
    env.db.refresh(rule_a)
    env.db.refresh(rule_b)

    response = env.client.get(
        "/api/v1/automation-rules/",
        headers=_auth(env.tokens["a"]),
    )
    assert response.status_code == 200
    assert [rule["id"] for rule in response.json()] == [rule_a.id]

    response = env.client.patch(
        f"/api/v1/automation-rules/{rule_b.id}",
        headers=_auth(env.tokens["a"]),
        json={"enabled": False},
    )
    assert response.status_code == 404

    response = env.client.delete(
        f"/api/v1/automation-rules/{rule_b.id}",
        headers=_auth(env.tokens["a"]),
    )
    assert response.status_code == 404
    env.db.expire_all()
    assert env.db.get(AutomationRule, rule_b.id).enabled is True

    # Engine path: the incident tenant is the only source of rules.
    incident_a = _seed_incident(
        env.db,
        env.tenants["a"].id,
        title="A automation incident",
        severity=Severity.HIGH,
    )
    AutomationEngine().run(incident_a, env.db)

    runs = env.db.query(AutomationRun).all()
    assert len(runs) == 1
    assert runs[0].tenant_id == env.tenants["a"].id
    assert runs[0].incident_id == incident_a.id


def test_server_side_webhook_test_uses_principal_tenant(tenant_env):
    env = tenant_env

    response = env.client.post(
        "/api/v1/webhooks/test",
        headers=_auth(env.tokens["a"]),
        json={
            "provider": "custom",
            "payload": {
                "title": "A webhook drill",
                "message": "drill from tenant A",
                "severity": "HIGH",
            },
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1

    env.db.expire_all()
    created = env.db.get(Incident, body[0]["id"])
    assert created is not None
    assert created.tenant_id == env.tenants["a"].id
    env.dispatch.assert_called()


def test_webhook_secret_and_slug_validation(tenant_env):
    env = tenant_env
    payload = {
        "title": "Webhook isolation",
        "message": "webhook test",
        "severity": "HIGH",
    }

    def call(
        *,
        slug: str | None,
        secret: str | None,
        title: str = "Webhook isolation",
    ):
        headers = {}
        if slug is not None:
            headers["X-Tenant-Slug"] = slug
        if secret is not None:
            headers["X-Webhook-Secret"] = secret
        body = dict(payload)
        body["title"] = title
        return env.client.post(
            "/api/v1/webhooks/custom",
            headers=headers,
            json=body,
        )

    response = call(slug="tenant-a", secret="secret-a", title="A webhook")
    assert response.status_code == 200
    env.db.expire_all()
    assert env.db.get(Incident, response.json()[0]["id"]).tenant_id == env.tenants["a"].id

    response = call(slug="tenant-a", secret="secret-b", title="wrong A secret")
    assert response.status_code == 401

    response = call(slug="tenant-b", secret="secret-a", title="wrong B secret")
    assert response.status_code == 401

    response = call(
        slug="tenant-a",
        secret=settings.WEBHOOK_SECRET,
        title="global secret on tenant A",
    )
    assert response.status_code == 401

    response = call(
        slug="does-not-exist",
        secret=settings.WEBHOOK_SECRET,
        title="unknown slug",
    )
    assert response.status_code == 401

    response = call(
        slug="",
        secret=settings.WEBHOOK_SECRET,
        title="empty slug",
    )
    assert response.status_code == 401

    response = call(
        slug="tenant-inactive",
        secret="secret-inactive",
        title="inactive tenant",
    )
    assert response.status_code == 403

    response = call(slug=None, secret=None, title="missing secret")
    assert response.status_code == 401

    response = call(
        slug=None,
        secret=settings.WEBHOOK_SECRET,
        title="global default",
    )
    assert response.status_code == 200
    env.db.expire_all()
    assert env.db.get(Incident, response.json()[0]["id"]).tenant_id == env.tenants["default"].id

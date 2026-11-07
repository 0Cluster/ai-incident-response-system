"""Tests for the LangGraph investigation workflow."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.core.auth as auth
import app.core.dependencies as deps
from app.main import app
from app.agent.state import InvestigationState
from app.agent.workflow import build_workflow
from app.models.enums import (
    AnalysisStatus,
    AutomationStatus,
    IncidentSource,
    IncidentStatus,
    Severity,
    UserRole,
)
from app.models.automation_rule import AutomationRule
from app.models.incident import Incident
from app.models.tenant import Tenant
from app.models.user import User
from app.models.workflow_state import WorkflowState


def _sqlite_session_factory() -> sessionmaker:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Tenant.__table__.create(engine)
    User.__table__.create(engine)
    Incident.__table__.create(engine)
    AutomationRule.__table__.create(engine)
    WorkflowState.__table__.create(engine)
    return sessionmaker(
        bind=engine, autoflush=False, autocommit=False
    )


def _seed_default_tenant(SessionLocal: sessionmaker) -> int:
    db: Session = SessionLocal()
    try:
        tenant = Tenant(slug="default", name="Default", is_active=True)
        db.add(tenant)
        db.commit()
        db.refresh(tenant)
        return tenant.id
    finally:
        db.close()


def _seed_incident(
    SessionLocal: sessionmaker,
    tenant_id: int,
    title: str = "Database down",
    message: str = "primary database unavailable",
    status: IncidentStatus = IncidentStatus.OPEN,
) -> Incident:
    db: Session = SessionLocal()
    try:
        incident = Incident(
            tenant_id=tenant_id,
            title=title,
            message=message,
            status=status,
            analysis_status=AnalysisStatus.PENDING,
            automation_status=AutomationStatus.PENDING,
            severity=Severity.HIGH,
            source=IncidentSource.MANUAL,
        )
        db.add(incident)
        db.commit()
        db.refresh(incident)
        return incident
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
        user = User(
            email=email,
            tenant_id=tenant_id,
            password_hash="hash",
            role=role,
            is_active=True,
            is_superadmin=False,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user
    finally:
        db.close()


def test_workflow_builds_and_compiles():
    """The LangGraph workflow should build and compile without errors."""
    graph = build_workflow()
    compiled = graph.compile()
    assert compiled is not None


def test_workflow_run_creates_state():
    """Running the workflow should produce a valid InvestigationState."""
    graph = build_workflow().compile()

    state = InvestigationState(
        incident_id=1,
        tenant_id=1,
        actor_user_id=1,
        actor_email="test@example.com",
        created_at=datetime.now(timezone.utc).isoformat(),
        updated_at=datetime.now(timezone.utc).isoformat(),
    )

    # This will fail at load_incident because there's no incident in the DB,
    # but the graph should execute without crashing the compile/run layer.
    result = graph.invoke(state)

    assert "workflow_status" in result
    assert "current_step" in result
    assert "steps_completed" in result


def test_start_investigation_api_endpoint():
    """POST /api/v1/investigations/{id}/start should start a workflow."""
    SessionLocal = _sqlite_session_factory()
    db: Session = SessionLocal()
    try:
        tenant_id = _seed_default_tenant(SessionLocal)
        incident = _seed_incident(SessionLocal, tenant_id)
        _seed_user(SessionLocal, tenant_id, "responder@example.com", UserRole.RESPONDER)

        def override_get_db():
            try:
                yield db
            finally:
                pass

        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(auth.settings, "AUTH_REQUIRED", False)
        monkeypatch.setattr(auth.settings, "API_KEY", "")
        app.dependency_overrides[deps.get_db] = override_get_db
        try:
            client = TestClient(app)
            with patch(
                "app.api.routes.investigation.run_investigation.delay"
            ) as delay:
                response = client.post(
                    f"/api/v1/investigations/{incident.id}/start",
                )
            # With AUTH_REQUIRED=false and no API_KEY, anonymous users get
            # synthetic ADMIN principal, so this should succeed
            assert response.status_code in (200, 202)
            delay.assert_called_once()
            assert delay.call_args.kwargs["resume"] is False
            assert delay.call_args.kwargs["run_id"]
        finally:
            app.dependency_overrides.clear()
            monkeypatch.undo()
    finally:
        db.close()


def test_start_rejects_running_investigation():
    """A second start must not silently lose the new run on the worker lock."""
    SessionLocal = _sqlite_session_factory()
    db: Session = SessionLocal()
    try:
        tenant_id = _seed_default_tenant(SessionLocal)
        incident = _seed_incident(SessionLocal, tenant_id)
        state = InvestigationState(
            incident_id=incident.id,
            tenant_id=tenant_id,
            run_id="existing-run",
            workflow_status="in_progress",
            current_step="load_incident",
        )
        db.add(
            WorkflowState(
                incident_id=state.incident_id,
                tenant_id=state.tenant_id,
                state_json=state.model_dump(),
                status=state.workflow_status,
                current_step=state.current_step,
                updated_at=datetime.now(timezone.utc),
            )
        )
        db.commit()

        def override_get_db():
            try:
                yield db
            finally:
                pass

        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(auth.settings, "AUTH_REQUIRED", False)
        monkeypatch.setattr(auth.settings, "API_KEY", "")
        app.dependency_overrides[deps.get_db] = override_get_db
        try:
            client = TestClient(app)
            with patch(
                "app.api.routes.investigation.run_investigation.delay"
            ) as delay:
                response = client.post(
                    f"/api/v1/investigations/{incident.id}/start",
                )
            assert response.status_code == 409
            delay.assert_not_called()
        finally:
            app.dependency_overrides.clear()
            monkeypatch.undo()
    finally:
        db.close()


def test_approval_requires_waiting_state():
    """Approval cannot resume an in-progress or failed state."""
    SessionLocal = _sqlite_session_factory()
    db: Session = SessionLocal()
    try:
        tenant_id = _seed_default_tenant(SessionLocal)
        incident = _seed_incident(SessionLocal, tenant_id)
        state = InvestigationState(
            incident_id=incident.id,
            tenant_id=tenant_id,
            run_id="running-run",
            requires_approval=True,
            approved=None,
            workflow_status="in_progress",
            current_step="execute_approved_action",
        )
        db.add(
            WorkflowState(
                incident_id=state.incident_id,
                tenant_id=state.tenant_id,
                state_json=state.model_dump(),
                status=state.workflow_status,
                current_step=state.current_step,
            )
        )
        db.commit()

        def override_get_db():
            try:
                yield db
            finally:
                pass

        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(auth.settings, "AUTH_REQUIRED", False)
        monkeypatch.setattr(auth.settings, "API_KEY", "")
        app.dependency_overrides[deps.get_db] = override_get_db
        try:
            client = TestClient(app)
            with patch(
                "app.api.routes.investigation.run_investigation.delay"
            ) as delay:
                response = client.post(
                    f"/api/v1/investigations/{incident.id}/approve",
                    json={"approved": True, "reason": "stale"},
                )
            assert response.status_code == 409
            delay.assert_not_called()
        finally:
            app.dependency_overrides.clear()
            monkeypatch.undo()
    finally:
        db.close()


def test_approval_workflow_starts_at_execution():
    """The approval graph must not re-run analysis or planning."""
    from app.agent.workflow import build_approval_workflow

    graph = build_approval_workflow().compile()
    nodes = set(graph.get_graph().nodes)
    assert "execute_approved_action" in nodes
    assert "load_incident" not in nodes
    assert "analyze_incident" not in nodes
    assert "create_remediation_plan" not in nodes


def test_investigation_state_model():
    """InvestigationState should serialize/deserialize correctly."""
    state = InvestigationState(
        incident_id=1,
        tenant_id=1,
        actor_user_id=1,
        actor_email="test@example.com",
        risk_level="destructive",
        requires_approval=True,
        remediation_plan="Restart the database",
    )
    assert state.incident_id == 1
    assert state.risk_level == "destructive"
    assert state.requires_approval is True
    assert state.approved is None

    d = state.model_dump()
    assert d["incident_id"] == 1
    assert d["risk_level"] == "destructive"


def test_allowlist_blocks_script_action():
    """Script action must be in BLOCKED_ACTIONS and never allowed."""
    from app.agent.workflow import BLOCKED_ACTIONS, ALLOWLISTED_ACTIONS

    assert "script" in BLOCKED_ACTIONS
    assert "script" not in ALLOWLISTED_ACTIONS
    assert "slack" in BLOCKED_ACTIONS
    assert "log" in ALLOWLISTED_ACTIONS
    assert "webhook" in ALLOWLISTED_ACTIONS


def test_workflow_state_persistence():
    """WorkflowState should persist and load from DB."""
    SessionLocal = _sqlite_session_factory()
    db: Session = SessionLocal()
    try:
        _seed_default_tenant(SessionLocal)
        _seed_incident(SessionLocal, 1)

        state = InvestigationState(
            incident_id=1,
            tenant_id=1,
            actor_user_id=1,
            actor_email="test@example.com",
            risk_level="destructive",
            requires_approval=True,
            remediation_plan="Restart the database",
            workflow_status="waiting_for_approval",
            current_step="wait_for_approval",
        )

        # Persist
        row = WorkflowState(
            incident_id=state.incident_id,
            tenant_id=state.tenant_id,
            state_json=state.model_dump(),
            status=state.workflow_status,
            current_step=state.current_step,
        )
        db.add(row)
        db.commit()

        # Load back
        loaded = (
            db.query(WorkflowState)
            .filter(WorkflowState.incident_id == 1)
            .order_by(WorkflowState.updated_at.desc())
            .first()
        )
        assert loaded is not None
        assert loaded.state_json["incident_id"] == 1
        assert loaded.state_json["risk_level"] == "destructive"
        assert loaded.state_json["requires_approval"] is True
        assert loaded.status == "waiting_for_approval"
    finally:
        db.close()


def test_start_investigation_requires_existing_incident():
    """Starting an investigation for a non-existent incident returns 404."""
    SessionLocal = _sqlite_session_factory()
    db: Session = SessionLocal()
    try:
        _seed_default_tenant(SessionLocal)

        def override_get_db():
            try:
                yield db
            finally:
                pass

        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(auth.settings, "AUTH_REQUIRED", False)
        monkeypatch.setattr(auth.settings, "API_KEY", "")
        app.dependency_overrides[deps.get_db] = override_get_db
        try:
            client = TestClient(app)
            response = client.post("/api/v1/investigations/99999/start")
            assert response.status_code == 404
        finally:
            app.dependency_overrides.clear()
            monkeypatch.undo()
    finally:
        db.close()


def test_investigation_approval_flow():
    """Approve/reject flow through the API."""
    SessionLocal = _sqlite_session_factory()
    db: Session = SessionLocal()
    try:
        tenant_id = _seed_default_tenant(SessionLocal)
        incident = _seed_incident(SessionLocal, tenant_id)

        # Manually create a waiting_for_approval state
        state = InvestigationState(
            incident_id=incident.id,
            tenant_id=tenant_id,
            actor_user_id=1,
            actor_email="responder@example.com",
            risk_level="destructive",
            requires_approval=True,
            remediation_plan="Restart the database",
            workflow_status="waiting_for_approval",
            current_step="wait_for_approval",
        )
        row = WorkflowState(
            incident_id=state.incident_id,
            tenant_id=state.tenant_id,
            state_json=state.model_dump(),
            status=state.workflow_status,
            current_step=state.current_step,
        )
        db.add(row)
        db.commit()

        def override_get_db():
            try:
                yield db
            finally:
                pass

        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(auth.settings, "AUTH_REQUIRED", False)
        monkeypatch.setattr(auth.settings, "API_KEY", "")
        app.dependency_overrides[deps.get_db] = override_get_db
        try:
            client = TestClient(app)

            # Approve
            with patch(
                "app.api.routes.investigation.run_investigation.delay"
            ) as delay:
                response = client.post(
                    f"/api/v1/investigations/{incident.id}/approve",
                    json={"approved": True, "reason": "Looks safe"},
                )
            assert response.status_code == 200
            body = response.json()
            assert body["approved"] is True
            delay.assert_called_once()
            assert delay.call_args.kwargs["resume"] is True
            assert delay.call_args.kwargs["run_id"]

            # Reload state and verify approval was recorded
            db.expire_all()  # Force refresh from database after API commit
            rows = (
                db.query(WorkflowState)
                .filter(WorkflowState.incident_id == incident.id)
                .order_by(WorkflowState.id.desc())
                .all()
            )
            assert len(rows) >= 1
            assert any(r.state_json["approved"] is True for r in rows), (
                f"No row with approved=True. Rows: {[r.state_json for r in rows]}"
            )
            loaded = rows[0]
            assert loaded.state_json["approval_reason"] == "Looks safe"

            # Re-test: approval already recorded should return 400
            response2 = client.post(
                f"/api/v1/investigations/{incident.id}/approve",
                json={"approved": True, "reason": "Again"},
            )
            assert response2.status_code == 400
        finally:
            app.dependency_overrides.clear()
            monkeypatch.undo()
    finally:
        db.close()


def test_workflow_does_not_loop_on_insufficient_evidence():
    """Investigation runs at most once before planning proceeds."""
    from app.agent.workflow import evidence_sufficient_decision

    state = InvestigationState(
        incident_id=1,
        tenant_id=1,
        evidence_sufficient=False,
    )
    # First pass with insufficient evidence triggers investigation.
    assert evidence_sufficient_decision(state) == "investigate"

    # Once investigation has run, proceed instead of looping forever.
    state.steps_completed.append("investigate")
    assert evidence_sufficient_decision(state) == "create_remediation_plan"


def test_list_investigations_returns_latest_state_per_incident():
    """The approvals queue lists only the latest state for each incident."""
    from app.api.routes.investigation import list_investigations

    SessionLocal = _sqlite_session_factory()
    db: Session = SessionLocal()
    try:
        tenant_id = _seed_default_tenant(SessionLocal)
        waiting = _seed_incident(SessionLocal, tenant_id, title="Waiting incident")
        done = _seed_incident(SessionLocal, tenant_id, title="Done incident")

        # An older waiting row for `done` must not override its completed state.
        old = InvestigationState(
            incident_id=done.id,
            tenant_id=tenant_id,
            workflow_status="waiting_for_approval",
            current_step="wait_for_approval",
            requires_approval=True,
        )
        db.add(
            WorkflowState(
                incident_id=old.incident_id,
                tenant_id=old.tenant_id,
                state_json=old.model_dump(),
                status=old.workflow_status,
                current_step=old.current_step,
            )
        )
        db.commit()
        new = InvestigationState(
            incident_id=done.id,
            tenant_id=tenant_id,
            workflow_status="completed",
            current_step="end",
        )
        db.add(
            WorkflowState(
                incident_id=new.incident_id,
                tenant_id=new.tenant_id,
                state_json=new.model_dump(),
                status=new.workflow_status,
                current_step=new.current_step,
            )
        )
        db.commit()

        pending = InvestigationState(
            incident_id=waiting.id,
            tenant_id=tenant_id,
            incident_title="Waiting incident",
            incident_severity="HIGH",
            workflow_status="waiting_for_approval",
            current_step="wait_for_approval",
            requires_approval=True,
        )
        db.add(
            WorkflowState(
                incident_id=pending.incident_id,
                tenant_id=pending.tenant_id,
                state_json=pending.model_dump(),
                status=pending.workflow_status,
                current_step=pending.current_step,
            )
        )
        db.commit()

        principal = auth.Principal(
            user_id=None,
            email="admin@example.com",
            role=UserRole.ADMIN,
            auth_type="anonymous",
            tenant_id=tenant_id,
            tenant_slug="default",
            is_superadmin=False,
        )
        rows = list_investigations(
            status_filter="waiting_for_approval",
            principal=principal,
            db=db,
        )
        assert [row.incident_id for row in rows] == [waiting.id]
        assert rows[0].incident_title == "Waiting incident"
    finally:
        db.close()

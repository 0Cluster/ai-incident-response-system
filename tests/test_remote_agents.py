"""Remote agent identity, job lifecycle, and investigation integration tests."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.core.auth as auth
import app.core.dependencies as deps
from app.agent.state import InvestigationState
from app.core.auth import Principal
from app.main import app
from app.models.enums import (
    IncidentSource,
    IncidentStatus,
    RemoteApprovalStatus,
    RemoteAgentStatus,
    RemoteExecutionType,
    RemoteJobStatus,
    Severity,
    UserRole,
)
from app.models.incident import Incident
from app.models.outbox import OutboxEvent
from app.models.remote_agent import (
    RemoteAgent,
    RemoteAgentCredential,
    RemoteAgentEvent,
)
from app.models.remote_job import (
    RemoteJob,
    RemoteJobApproval,
    RemoteJobEvent,
    RemoteJobResult,
)
from app.models.runbook import Runbook
from app.models.tenant import Tenant
from app.models.user import ApiToken, User
from app.models.workflow_state import WorkflowState
from app.remote.planner import RemotePlanner
from app.schemas.remote import (
    JobResultRequest,
    RemoteAgentCreate,
)
from app.services.auth import AuthService
from app.services.remote_agent import RemoteAgentService
from app.services.remote_investigation import RemoteInvestigationService
from app.services.remote_job import RemoteJobExpiredError, RemoteJobService


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def remote_env(monkeypatch):
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
        WorkflowState,
        Runbook,
        OutboxEvent,
        RemoteAgent,
        RemoteAgentCredential,
        RemoteAgentEvent,
        RemoteJob,
        RemoteJobResult,
        RemoteJobApproval,
        RemoteJobEvent,
    ):
        table.__table__.create(engine)

    SessionLocal = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
    )
    db: Session = SessionLocal()

    tenant_a = Tenant(slug="tenant-a", name="Tenant A", is_active=True)
    tenant_b = Tenant(slug="tenant-b", name="Tenant B", is_active=True)
    db.add_all([tenant_a, tenant_b])
    db.commit()
    db.refresh(tenant_a)
    db.refresh(tenant_b)

    admin_a = User(
        email="admin-a@example.com",
        tenant_id=tenant_a.id,
        password_hash="hash",
        role=UserRole.ADMIN,
        is_active=True,
    )
    responder_a = User(
        email="responder-a@example.com",
        tenant_id=tenant_a.id,
        password_hash="hash",
        role=UserRole.RESPONDER,
        is_active=True,
    )
    viewer_a = User(
        email="viewer-a@example.com",
        tenant_id=tenant_a.id,
        password_hash="hash",
        role=UserRole.VIEWER,
        is_active=True,
    )
    admin_b = User(
        email="admin-b@example.com",
        tenant_id=tenant_b.id,
        password_hash="hash",
        role=UserRole.ADMIN,
        is_active=True,
    )
    db.add_all([admin_a, responder_a, viewer_a, admin_b])
    db.commit()
    for user in (admin_a, responder_a, viewer_a, admin_b):
        db.refresh(user)

    auth_service = AuthService(db)
    tokens = {
        "admin_a": auth_service.issue_token(admin_a)[0],
        "responder_a": auth_service.issue_token(responder_a)[0],
        "viewer_a": auth_service.issue_token(viewer_a)[0],
        "admin_b": auth_service.issue_token(admin_b)[0],
    }

    def override_get_db():
        yield db

    monkeypatch.setattr(auth.settings, "AUTH_REQUIRED", True)
    monkeypatch.setattr(auth.settings, "API_KEY", "")
    app.dependency_overrides[deps.get_db] = override_get_db
    try:
        with (
            patch("app.api.routes.investigation.run_investigation.delay"),
            patch("app.api.routes.investigation.run_remote_investigation.delay"),
            patch("app.pipelines.incident.dispatch_outbox.delay"),
            patch("app.tasks.outbox.dispatch_outbox.delay"),
        ):
            yield SimpleNamespace(
                client=TestClient(app),
                db=db,
                SessionLocal=SessionLocal,
                tenant_a=tenant_a,
                tenant_b=tenant_b,
                admin_a=admin_a,
                responder_a=responder_a,
                viewer_a=viewer_a,
                admin_b=admin_b,
                tokens=tokens,
            )
    finally:
        app.dependency_overrides.clear()
        db.close()
        engine.dispose()


def _seed_incident(
    db: Session,
    tenant_id: int,
    *,
    target_agent_id: int | None = None,
    title: str = "High memory usage",
    message: str = "memory usage is 95% on the target host",
) -> Incident:
    incident = Incident(
        tenant_id=tenant_id,
        target_agent_id=target_agent_id,
        title=title,
        message=message,
        status=IncidentStatus.OPEN,
        source=IncidentSource.GRAFANA,
        severity=Severity.HIGH,
    )
    db.add(incident)
    db.commit()
    db.refresh(incident)
    return incident


def _create_agent(
    db: Session,
    tenant_id: int,
    *,
    hostname: str = "target-1",
):
    return RemoteAgentService(db).create(
        tenant_id,
        RemoteAgentCreate(
            display_name=hostname,
            hostname=hostname,
            agent_key=hostname,
        ),
    )


def test_agent_credentials_are_hashed_and_revocation_blocks_auth(remote_env):
    env = remote_env
    agent, raw_token, credential = _create_agent(
        env.db,
        env.tenant_a.id,
    )

    stored = env.db.get(RemoteAgentCredential, credential.id)
    assert stored is not None
    assert stored.token_hash != raw_token
    assert len(stored.token_hash) == 64

    response = env.client.post(
        "/api/v1/agent/heartbeat",
        headers=_auth(raw_token),
        json={"version": "0.1.0", "hostname": "target-1"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["agent_id"] == agent.id

    env.db.expire_all()
    refreshed = env.db.get(RemoteAgent, agent.id)
    assert refreshed.last_seen_at is not None

    revoke = env.client.post(
        f"/api/v1/agents/{agent.id}/revoke",
        headers=_auth(env.tokens["admin_a"]),
    )
    assert revoke.status_code == 200, revoke.text
    assert revoke.json()["status"] == "REVOKED"

    denied = env.client.post(
        "/api/v1/agent/heartbeat",
        headers=_auth(raw_token),
        json={},
    )
    assert denied.status_code == 401


def test_agent_management_is_admin_only_and_tenant_scoped(remote_env):
    env = remote_env
    response = env.client.post(
        "/api/v1/agents",
        headers=_auth(env.tokens["admin_a"]),
        json={
            "display_name": "target-a",
            "hostname": "target-a",
            "agent_key": "target-a",
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    agent_id = body["agent"]["id"]
    raw_token = body["token"]
    assert body["agent"]["tenant_id"] == env.tenant_a.id
    assert raw_token

    viewer = env.client.post(
        "/api/v1/agents",
        headers=_auth(env.tokens["viewer_a"]),
        json={"display_name": "nope", "hostname": "nope"},
    )
    assert viewer.status_code == 403

    other_tenant = env.client.get(
        f"/api/v1/agents/{agent_id}",
        headers=_auth(env.tokens["admin_b"]),
    )
    assert other_tenant.status_code == 404

    other_tenant_rotate = env.client.post(
        f"/api/v1/agents/{agent_id}/rotate-credential",
        headers=_auth(env.tokens["admin_b"]),
    )
    assert other_tenant_rotate.status_code == 404

    rotated = env.client.post(
        f"/api/v1/agents/{agent_id}/rotate-credential",
        headers=_auth(env.tokens["admin_a"]),
    )
    assert rotated.status_code == 200, rotated.text
    new_token = rotated.json()["token"]
    assert new_token != raw_token

    old_denied = env.client.post(
        "/api/v1/agent/heartbeat",
        headers=_auth(raw_token),
        json={},
    )
    assert old_denied.status_code == 401
    new_ok = env.client.post(
        "/api/v1/agent/heartbeat",
        headers=_auth(new_token),
        json={},
    )
    assert new_ok.status_code == 200


def test_agent_job_lease_ack_result_and_duplicate_are_idempotent(remote_env):
    env = remote_env
    agent, token, credential = _create_agent(env.db, env.tenant_a.id)
    incident = _seed_incident(
        env.db,
        env.tenant_a.id,
        target_agent_id=agent.id,
    )
    job = RemoteJobService(env.db).create_job(
        tenant_id=env.tenant_a.id,
        incident_id=incident.id,
        agent_id=agent.id,
        action_id="inspect_memory",
        parameters={},
        execution_type=RemoteExecutionType.DIAGNOSTIC,
        run_id="run-1",
        commit=True,
    )
    assert job.status == RemoteJobStatus.APPROVED

    poll = env.client.post(
        "/api/v1/agent/jobs/poll",
        headers=_auth(token),
        json={"max_jobs": 1},
    )
    assert poll.status_code == 200, poll.text
    leased = poll.json()["job"]
    assert leased["id"] == job.id
    assert leased["lease_id"]
    assert "approval" not in leased
    assert "tenant_id" not in leased
    assert "idempotency_key" not in leased

    ack = env.client.post(
        f"/api/v1/agent/jobs/{job.id}/ack",
        headers=_auth(token),
        json={"lease_id": leased["lease_id"]},
    )
    assert ack.status_code == 200, ack.text
    assert ack.json()["status"] == "ACKNOWLEDGED"

    result_payload = {
        "lease_id": leased["lease_id"],
        "status": "SUCCEEDED",
        "exit_code": 0,
        "stdout": "password=hunter2 used_percent=95",
        "structured_output": {
            "used_percent": 95,
            "detail": "token=hunter3",
        },
        "duration_ms": 12,
    }
    result = env.client.post(
        f"/api/v1/agent/jobs/{job.id}/result",
        headers=_auth(token),
        json=result_payload,
    )
    assert result.status_code == 200, result.text
    body = result.json()
    assert body["status"] == "SUCCEEDED"
    assert "hunter2" not in body["stdout_redacted"]
    assert "[REDACTED]" in body["stdout_redacted"]
    assert body["structured_output"]["used_percent"] == 95
    assert "hunter3" not in body["structured_output"]["detail"]

    duplicate = env.client.post(
        f"/api/v1/agent/jobs/{job.id}/result",
        headers=_auth(token),
        json=result_payload,
    )
    assert duplicate.status_code == 200, duplicate.text
    assert duplicate.json()["id"] == body["id"]

    env.db.expire_all()
    stored_job = env.db.get(RemoteJob, job.id)
    assert stored_job.status == RemoteJobStatus.SUCCEEDED
    events = list(
        env.db.scalars(
            select(OutboxEvent).where(
                OutboxEvent.idempotency_key == f"remote_result:{job.id}"
            )
        ).all()
    )
    assert len(events) == 1

    no_more = env.client.post(
        "/api/v1/agent/jobs/poll",
        headers=_auth(token),
        json={"max_jobs": 1},
    )
    assert no_more.status_code == 200
    assert no_more.json()["job"] is None

    # Another tenant's agent cannot lease or read the job.
    other_agent, other_token, _ = _create_agent(
        env.db,
        env.tenant_b.id,
        hostname="target-b",
    )
    other_poll = env.client.post(
        "/api/v1/agent/jobs/poll",
        headers=_auth(other_token),
        json={"max_jobs": 1},
    )
    assert other_poll.status_code == 200
    assert other_poll.json()["job"] is None

    human_read = env.client.get(
        f"/api/v1/remote-jobs/{job.id}",
        headers=_auth(env.tokens["viewer_a"]),
    )
    assert human_read.status_code == 200, human_read.text
    assert "lease_id" not in human_read.json()
    assert "idempotency_key" not in human_read.json()

    other_read = env.client.get(
        f"/api/v1/remote-jobs/{job.id}",
        headers=_auth(env.tokens["admin_b"]),
    )
    assert other_read.status_code == 404


def test_remote_approval_is_bound_to_exact_job_and_tenant(remote_env):
    env = remote_env
    agent, token, _ = _create_agent(env.db, env.tenant_a.id)
    incident = _seed_incident(
        env.db,
        env.tenant_a.id,
        target_agent_id=agent.id,
    )
    service = RemoteJobService(env.db)
    job = service.create_job(
        tenant_id=env.tenant_a.id,
        incident_id=incident.id,
        agent_id=agent.id,
        action_id="restart_service",
        parameters={"service": "airs-demo-app"},
        execution_type=RemoteExecutionType.REMEDIATION,
        run_id="run-approval",
        commit=True,
    )
    approval = env.db.scalar(
        select(RemoteJobApproval).where(RemoteJobApproval.job_id == job.id)
    )
    assert approval is not None
    assert approval.status == RemoteApprovalStatus.PENDING
    assert approval.action_hash

    state = InvestigationState(
        incident_id=incident.id,
        tenant_id=env.tenant_a.id,
        run_id="run-approval",
        target_agent_id=agent.id,
        mode="remote",
        workflow_status="waiting_for_approval",
        current_step="wait_for_approval",
        pending_job_ids=[job.id],
        requires_approval=True,
    )
    env.db.add(
        WorkflowState(
            incident_id=incident.id,
            tenant_id=env.tenant_a.id,
            state_json=state.model_dump(),
            status=state.workflow_status,
            current_step=state.current_step,
        )
    )
    env.db.commit()

    wrong = env.client.post(
        f"/api/v1/remote-jobs/{job.id}/approve",
        headers=_auth(env.tokens["responder_a"]),
        json={
            "approved": True,
            "reason": "wrong hash",
            "action_hash": "0" * 64,
        },
    )
    assert wrong.status_code == 409

    other_tenant = env.client.post(
        f"/api/v1/remote-jobs/{job.id}/approve",
        headers=_auth(env.tokens["admin_b"]),
        json={"approved": True, "reason": "cross-tenant"},
    )
    assert other_tenant.status_code == 404

    approved = env.client.post(
        f"/api/v1/remote-jobs/{job.id}/approve",
        headers=_auth(env.tokens["responder_a"]),
        json={
            "approved": True,
            "reason": "lab change window",
            "action_hash": approval.action_hash,
        },
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "APPROVED"

    env.db.expire_all()
    stored = env.db.get(RemoteJob, job.id)
    assert stored.status == RemoteJobStatus.APPROVED
    assert stored.approved_at is not None


def _latest_state(db: Session, incident_id: int) -> InvestigationState:
    row = db.scalar(
        select(WorkflowState)
        .where(WorkflowState.incident_id == incident_id)
        .order_by(WorkflowState.id.desc())
        .limit(1)
    )
    assert row is not None
    return InvestigationState(**row.state_json)


def _lease_and_submit(
    db: Session,
    agent_id: int,
    tenant_id: int,
    action_id: str,
    output: dict,
) -> RemoteJob:
    jobs = RemoteJobService(db)
    leased = jobs.lease_next(tenant_id=tenant_id, agent_id=agent_id)
    assert leased is not None
    assert leased.action_id == action_id
    jobs.acknowledge(
        tenant_id=tenant_id,
        agent_id=agent_id,
        job_id=leased.id,
        lease_id=leased.lease_id,
    )
    jobs.submit_result(
        tenant_id=tenant_id,
        agent_id=agent_id,
        job_id=leased.id,
        data=JobResultRequest(
            lease_id=leased.lease_id,
            status="SUCCEEDED",
            exit_code=0,
            structured_output=output,
        ),
    )
    return leased


def test_remote_investigation_diagnose_approve_and_verify(remote_env):
    env = remote_env
    agent, token, _ = _create_agent(env.db, env.tenant_a.id)
    incident = _seed_incident(
        env.db,
        env.tenant_a.id,
        target_agent_id=agent.id,
    )
    state = InvestigationState(
        incident_id=incident.id,
        tenant_id=env.tenant_a.id,
        run_id="run-e2e",
        target_agent_id=agent.id,
        mode="remote",
        actor_user_id=env.responder_a.id,
        actor_email=env.responder_a.email,
    )
    service = RemoteInvestigationService(
        env.db,
        planner=RemotePlanner(allow_llm=False),
    )
    service.start(state)
    assert state.workflow_status == "waiting_for_agent"
    assert state.pending_job_ids

    principal = Principal(
        user_id=env.responder_a.id,
        email=env.responder_a.email,
        role=UserRole.RESPONDER,
        auth_type="bearer",
        tenant_id=env.tenant_a.id,
        tenant_slug=env.tenant_a.slug,
    )

    for _ in range(20):
        current = _latest_state(env.db, incident.id)
        if not current.pending_job_ids:
            break
        if current.workflow_status == "waiting_for_approval":
            job = env.db.get(RemoteJob, current.pending_job_ids[0])
            assert job is not None
            assert job.action_id == "terminate_process"
            with pytest.raises(Exception):
                service.approve(
                    job_id=job.id,
                    principal=principal,
                    approved=True,
                    provided_action_hash="f" * 64,
                )
            service.approve(
                job_id=job.id,
                principal=principal,
                approved=True,
                reason="approved memory-hog termination",
                provided_action_hash=job.approval.action_hash,
            )
            continue

        pending_job = env.db.get(RemoteJob, current.pending_job_ids[0])
        assert pending_job is not None
        if (
            pending_job.action_id == "inspect_memory"
            and pending_job.execution_type == RemoteExecutionType.VERIFICATION
        ):
            output = {"used_percent": 52}
        elif pending_job.action_id == "inspect_memory":
            output = {"used_percent": 95, "total_bytes": 100, "used_bytes": 95}
        elif pending_job.action_id == "list_memory_processes":
            output = {
                "processes": [
                    {
                        "pid": 4242,
                        "user": "app",
                        "rss_bytes": 80,
                        "command": "/usr/bin/python worker.py",
                    }
                ]
            }
        elif pending_job.action_id == "inspect_process":
            output = {
                "pid": 4242,
                "user": "app",
                "start_time": "2026-11-08T00:00:00+00:00",
                "command": "/usr/bin/python worker.py",
            }
        elif pending_job.action_id == "terminate_process":
            output = {
                "pid": 4242,
                "user": "app",
                "start_time": "2026-11-08T00:00:00+00:00",
                "command": "/usr/bin/python worker.py",
                "terminated": True,
                "sigterm_sent": True,
                "sigkill_sent": False,
            }
        else:
            output = {"used_percent": 52}

        leased = _lease_and_submit(
            env.db,
            agent.id,
            env.tenant_a.id,
            pending_job.action_id,
            output,
        )
        service.process_job_result(leased.id)

    final = _latest_state(env.db, incident.id)
    assert final.workflow_status == "completed", final.model_dump_json(indent=2)
    assert final.verified is True
    assert final.service_healthy is True
    assert final.executed is True
    assert final.remote_action is not None

    env.db.expire_all()
    refreshed_incident = env.db.get(Incident, incident.id)
    assert refreshed_incident.status == IncidentStatus.RESOLVED

    approval = env.db.scalar(
        select(RemoteJobApproval).where(
            RemoteJobApproval.incident_id == incident.id
        )
    )
    assert approval is not None
    assert approval.status == RemoteApprovalStatus.APPROVED
    assert approval.approved_by == env.responder_a.id


def test_remote_incident_start_dispatches_remote_task(remote_env):
    env = remote_env
    agent, token, _ = _create_agent(env.db, env.tenant_a.id)
    incident = _seed_incident(
        env.db,
        env.tenant_a.id,
        target_agent_id=agent.id,
    )
    stale_job = RemoteJobService(env.db).create_job(
        tenant_id=env.tenant_a.id,
        incident_id=incident.id,
        agent_id=agent.id,
        action_id="restart_service",
        parameters={"service": "airs-demo-app"},
        execution_type=RemoteExecutionType.REMEDIATION,
        run_id="run-old",
        commit=True,
    )

    with (
        patch(
            "app.api.routes.investigation.run_remote_investigation.delay"
        ) as remote_delay,
        patch(
            "app.api.routes.investigation.run_investigation.delay"
        ) as local_delay,
    ):
        response = env.client.post(
            f"/api/v1/investigations/{incident.id}/start",
            headers=_auth(env.tokens["responder_a"]),
        )

    assert response.status_code == 202, response.text
    remote_delay.assert_called_once()
    local_delay.assert_not_called()
    env.db.expire_all()
    assert env.db.get(RemoteJob, stale_job.id).status == RemoteJobStatus.CANCELLED
    state = _latest_state(env.db, incident.id)
    assert state.mode == "remote"
    assert state.target_agent_id == agent.id


def test_grafana_agent_label_and_instance_fallback():
    from app.webhooks.adapters.grafana import GrafanaWebhookAdapter
    from app.webhooks.schemas import GrafanaWebhookRequest

    adapter = GrafanaWebhookAdapter()
    request = GrafanaWebhookRequest.model_validate(
        {
            "alerts": [
                {
                    "status": "firing",
                    "fingerprint": "fp-1",
                    "labels": {
                        "alertname": "HighMemory",
                        "agent_id": "target-1",
                        "instance": "target-1:9100",
                    },
                    "annotations": {"summary": "memory high"},
                },
                {
                    "status": "firing",
                    "fingerprint": "fp-2",
                    "labels": {
                        "alertname": "HighCPU",
                        "instance": "target-2:9100",
                    },
                    "annotations": {"summary": "cpu high"},
                },
            ]
        }
    )
    parsed = adapter.parse(request)
    assert parsed[0].incident.target_agent_ref == "target-1"
    assert parsed[1].incident.target_agent_ref == "target-2:9100"


def test_lease_recovery_never_replays_destructive_work(remote_env):
    env = remote_env
    agent, token, _ = _create_agent(env.db, env.tenant_a.id)
    incident = _seed_incident(
        env.db,
        env.tenant_a.id,
        target_agent_id=agent.id,
    )
    service = RemoteJobService(env.db)

    diagnostic = service.create_job(
        tenant_id=env.tenant_a.id,
        incident_id=incident.id,
        agent_id=agent.id,
        action_id="inspect_memory",
        parameters={},
        execution_type=RemoteExecutionType.DIAGNOSTIC,
        run_id="run-recover",
        commit=True,
    )
    leased = service.lease_next(
        tenant_id=env.tenant_a.id,
        agent_id=agent.id,
    )
    assert leased.id == diagnostic.id
    leased.lease_expires_at = leased.dispatched_at.replace(year=2000)
    env.db.commit()

    assert service.recover_expired_leases() == 1
    env.db.expire_all()
    recovered = env.db.get(RemoteJob, diagnostic.id)
    assert recovered.status == RemoteJobStatus.APPROVED
    recovered.status = RemoteJobStatus.CANCELLED
    recovered.completed_at = recovered.dispatched_at
    env.db.commit()

    remediation = service.create_job(
        tenant_id=env.tenant_a.id,
        incident_id=incident.id,
        agent_id=agent.id,
        action_id="restart_service",
        parameters={"service": "airs-demo-app"},
        execution_type=RemoteExecutionType.REMEDIATION,
        run_id="run-recover-destructive",
        commit=True,
    )
    # Approve directly at the service layer for this recovery test.
    remediation.status = RemoteJobStatus.APPROVED
    env.db.commit()
    leased = service.lease_next(
        tenant_id=env.tenant_a.id,
        agent_id=agent.id,
    )
    assert leased.id == remediation.id
    service.acknowledge(
        tenant_id=env.tenant_a.id,
        agent_id=agent.id,
        job_id=leased.id,
        lease_id=leased.lease_id,
    )
    leased.lease_expires_at = leased.dispatched_at.replace(year=2000)
    env.db.commit()

    assert service.recover_expired_leases() == 1
    env.db.expire_all()
    assert env.db.get(RemoteJob, remediation.id).status == RemoteJobStatus.UNKNOWN


def test_terminal_job_without_result_advances_investigation(remote_env):
    env = remote_env
    agent, token, _ = _create_agent(env.db, env.tenant_a.id)
    incident = _seed_incident(
        env.db,
        env.tenant_a.id,
        target_agent_id=agent.id,
    )
    jobs = RemoteJobService(env.db)
    investigation = RemoteInvestigationService(
        env.db,
        planner=RemotePlanner(allow_llm=False),
    )

    expired = jobs.create_job(
        tenant_id=env.tenant_a.id,
        incident_id=incident.id,
        agent_id=agent.id,
        action_id="inspect_memory",
        parameters={},
        execution_type=RemoteExecutionType.DIAGNOSTIC,
        run_id="run-expired",
        commit=True,
    )
    state = InvestigationState(
        incident_id=incident.id,
        tenant_id=env.tenant_a.id,
        run_id="run-expired",
        target_agent_id=agent.id,
        mode="remote",
        workflow_status="waiting_for_agent",
        current_step="await_remote_results",
        pending_job_ids=[expired.id],
    )
    env.db.add(
        WorkflowState(
            incident_id=incident.id,
            tenant_id=env.tenant_a.id,
            state_json=state.model_dump(),
            status=state.workflow_status,
            current_step=state.current_step,
        )
    )
    env.db.commit()
    expired.status = RemoteJobStatus.EXPIRED
    expired.last_error = "job expired before dispatch"
    env.db.commit()

    assert expired.id in jobs.unprocessed_terminal_job_ids()
    investigation.process_job_result(expired.id)

    failed = _latest_state(env.db, incident.id)
    assert failed.workflow_status == "failed"
    assert failed.pending_job_ids == []
    assert failed.evidence[-1]["status"] == "EXPIRED"
    env.db.expire_all()
    assert env.db.get(RemoteJob, expired.id).result_processed_at is not None

    unknown = jobs.create_job(
        tenant_id=env.tenant_a.id,
        incident_id=incident.id,
        agent_id=agent.id,
        action_id="restart_service",
        parameters={"service": "airs-demo-app"},
        execution_type=RemoteExecutionType.REMEDIATION,
        run_id="run-unknown",
        commit=True,
    )
    unknown_state = InvestigationState(
        incident_id=incident.id,
        tenant_id=env.tenant_a.id,
        run_id="run-unknown",
        target_agent_id=agent.id,
        mode="remote",
        workflow_status="waiting_for_agent",
        current_step="await_remote_results",
        pending_job_ids=[unknown.id],
        executed=True,
    )
    env.db.add(
        WorkflowState(
            incident_id=incident.id,
            tenant_id=env.tenant_a.id,
            state_json=unknown_state.model_dump(),
            status=unknown_state.workflow_status,
            current_step=unknown_state.current_step,
        )
    )
    env.db.commit()
    unknown.status = RemoteJobStatus.UNKNOWN
    unknown.last_error = "agent disappeared after acknowledgement"
    env.db.commit()

    investigation.process_job_result(unknown.id)

    reconciled = _latest_state(env.db, incident.id)
    assert reconciled.workflow_status == "failed"
    assert reconciled.pending_job_ids == []
    assert reconciled.executed is True
    assert "UNKNOWN" in (reconciled.execution_error or "")


def test_rejected_remote_action_does_not_get_reprocessed_as_failure(remote_env):
    env = remote_env
    agent, token, _ = _create_agent(env.db, env.tenant_a.id)
    incident = _seed_incident(
        env.db,
        env.tenant_a.id,
        target_agent_id=agent.id,
    )
    jobs = RemoteJobService(env.db)
    job = jobs.create_job(
        tenant_id=env.tenant_a.id,
        incident_id=incident.id,
        agent_id=agent.id,
        action_id="restart_service",
        parameters={"service": "airs-demo-app"},
        execution_type=RemoteExecutionType.REMEDIATION,
        run_id="run-reject",
        commit=True,
    )
    state = InvestigationState(
        incident_id=incident.id,
        tenant_id=env.tenant_a.id,
        run_id="run-reject",
        target_agent_id=agent.id,
        mode="remote",
        workflow_status="waiting_for_approval",
        current_step="wait_for_approval",
        pending_job_ids=[job.id],
    )
    env.db.add(
        WorkflowState(
            incident_id=incident.id,
            tenant_id=env.tenant_a.id,
            state_json=state.model_dump(),
            status=state.workflow_status,
            current_step=state.current_step,
        )
    )
    env.db.commit()

    principal = Principal(
        user_id=env.responder_a.id,
        email=env.responder_a.email,
        role=UserRole.RESPONDER,
        auth_type="bearer",
        tenant_id=env.tenant_a.id,
        tenant_slug=env.tenant_a.slug,
    )
    service = RemoteInvestigationService(
        env.db,
        planner=RemotePlanner(allow_llm=False),
    )
    service.approve(
        job_id=job.id,
        principal=principal,
        approved=False,
        reason="not during business hours",
    )
    rejected = _latest_state(env.db, incident.id)
    assert rejected.workflow_status == "completed"
    assert rejected.pending_job_ids == []

    service.process_job_result(job.id)
    still_completed = _latest_state(env.db, incident.id)
    assert still_completed.workflow_status == "completed"
    assert "rejected" in (still_completed.execution_error or "").lower()


def test_start_is_rejected_while_destructive_job_is_in_flight(remote_env):
    env = remote_env
    agent, token, _ = _create_agent(env.db, env.tenant_a.id)
    incident = _seed_incident(
        env.db,
        env.tenant_a.id,
        target_agent_id=agent.id,
    )
    job = RemoteJobService(env.db).create_job(
        tenant_id=env.tenant_a.id,
        incident_id=incident.id,
        agent_id=agent.id,
        action_id="restart_service",
        parameters={"service": "airs-demo-app"},
        execution_type=RemoteExecutionType.REMEDIATION,
        run_id="run-active",
        commit=True,
    )
    job.status = RemoteJobStatus.ACKNOWLEDGED
    env.db.commit()

    with patch(
        "app.api.routes.investigation.run_remote_investigation.delay"
    ) as remote_delay:
        response = env.client.post(
            f"/api/v1/investigations/{incident.id}/start",
            headers=_auth(env.tokens["responder_a"]),
        )

    assert response.status_code == 409, response.text
    remote_delay.assert_not_called()


def test_ack_rejects_an_expired_lease(remote_env):
    env = remote_env
    agent, token, _ = _create_agent(env.db, env.tenant_a.id)
    incident = _seed_incident(
        env.db,
        env.tenant_a.id,
        target_agent_id=agent.id,
    )
    service = RemoteJobService(env.db)
    job = service.create_job(
        tenant_id=env.tenant_a.id,
        incident_id=incident.id,
        agent_id=agent.id,
        action_id="inspect_memory",
        parameters={},
        execution_type=RemoteExecutionType.DIAGNOSTIC,
        run_id="run-expired-ack",
        commit=True,
    )
    leased = service.lease_next(
        tenant_id=env.tenant_a.id,
        agent_id=agent.id,
    )
    assert leased is not None and leased.id == job.id
    leased.lease_expires_at = leased.dispatched_at.replace(year=2000)
    env.db.commit()

    with pytest.raises(RemoteJobExpiredError):
        service.acknowledge(
            tenant_id=env.tenant_a.id,
            agent_id=agent.id,
            job_id=job.id,
            lease_id=leased.lease_id,
        )


def test_disabled_agent_can_be_reenabled_but_revoked_cannot(remote_env):
    env = remote_env
    agent, token, _ = _create_agent(env.db, env.tenant_a.id)

    disabled = env.client.post(
        f"/api/v1/agents/{agent.id}/disable",
        headers=_auth(env.tokens["admin_a"]),
    )
    assert disabled.status_code == 200, disabled.text
    assert disabled.json()["status"] == "DISABLED"
    denied = env.client.post(
        "/api/v1/agent/heartbeat",
        headers=_auth(token),
        json={},
    )
    assert denied.status_code == 401

    enabled = env.client.post(
        f"/api/v1/agents/{agent.id}/enable",
        headers=_auth(env.tokens["admin_a"]),
    )
    assert enabled.status_code == 200, enabled.text
    assert enabled.json()["status"] == "ACTIVE"
    accepted = env.client.post(
        "/api/v1/agent/heartbeat",
        headers=_auth(token),
        json={},
    )
    assert accepted.status_code == 200, accepted.text

    revoked = env.client.post(
        f"/api/v1/agents/{agent.id}/revoke",
        headers=_auth(env.tokens["admin_a"]),
    )
    assert revoked.status_code == 200, revoked.text
    cannot_enable = env.client.post(
        f"/api/v1/agents/{agent.id}/enable",
        headers=_auth(env.tokens["admin_a"]),
    )
    assert cannot_enable.status_code == 400


def test_alert_target_resolution_accepts_numeric_agent_id(remote_env):
    from app.repositories.incident import IncidentRepository
    from app.webhooks.service import WebhookService

    env = remote_env
    agent, _, _ = _create_agent(env.db, env.tenant_a.id)
    service = WebhookService(None, IncidentRepository(env.db))  # type: ignore[arg-type]

    resolved = service._resolve_target_agent(env.tenant_a.id, str(agent.id))
    assert resolved is not None and resolved.id == agent.id
    assert service._resolve_target_agent(env.tenant_b.id, str(agent.id)) is None


def test_alert_target_resolution_ignores_disabled_agents(remote_env):
    env = remote_env
    agent, _, _ = _create_agent(env.db, env.tenant_a.id)
    from app.repositories.incident import IncidentRepository
    from app.webhooks.service import WebhookService

    service = WebhookService(None, IncidentRepository(env.db))  # type: ignore[arg-type]
    env.db.get(RemoteAgent, agent.id).status = RemoteAgentStatus.DISABLED
    env.db.commit()

    assert service._resolve_target_agent(env.tenant_a.id, str(agent.id)) is None

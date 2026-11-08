"""Agentic investigation workflow endpoints.

Shadow mode: the workflow produces remediation plans and risk assessments,
but does not execute destructive actions without explicit human approval.
State is persisted to the ``workflow_states`` table so it survives worker
restarts and can be resumed after human approval.

All endpoints return immediately; the LangGraph graph runs asynchronously
via a Celery task so HTTP requests never block on AI analysis.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.agent.state import InvestigationState
from app.core.auth import Principal, get_current_principal, require_role
from app.core.dependencies import get_db
from app.core.security import rate_limit
from app.models.enums import RemoteAgentStatus, UserRole
from app.models.workflow_state import WorkflowState
from app.repositories.incident import IncidentRepository
from app.services.remote_agent import RemoteAgentService
from app.services.remote_job import RemoteJobService
from app.tasks.investigation import run_investigation
from app.tasks.remote import run_remote_investigation

router = APIRouter(prefix="/investigations", tags=["Investigation"])


def get_incident_repository(db: Session = Depends(get_db)) -> IncidentRepository:
    return IncidentRepository(db)


class InvestigationStartResponse(BaseModel):
    investigation_id: int
    workflow_status: str
    current_step: str


class InvestigationStatusResponse(BaseModel):
    investigation_id: int
    incident_id: int
    tenant_id: int
    incident_title: str = ""
    incident_severity: str = ""
    workflow_status: str
    current_step: str
    evidence_sufficient: bool
    risk_level: str
    requires_approval: bool
    approved: bool | None
    remediation_plan: str | None
    executed: bool
    verified: bool
    service_healthy: bool
    error: str | None
    steps_completed: list[str]
    mode: str = "local"
    target_agent_id: int | None = None
    investigation_round: int = 0
    pending_job_ids: list[int] = Field(default_factory=list)
    evidence: list[dict] = Field(default_factory=list)
    planner_reasoning: str = ""
    remote_action: dict | None = None
    remote_action_hash: str | None = None


class InvestigationApproveRequest(BaseModel):
    approved: bool
    reason: str = ""


class InvestigationApproveResponse(BaseModel):
    investigation_id: int
    approved: bool
    workflow_status: str
    message: str


def _state_to_response(state: InvestigationState) -> InvestigationStatusResponse:
    return InvestigationStatusResponse(
        investigation_id=state.incident_id,
        incident_id=state.incident_id,
        tenant_id=state.tenant_id,
        incident_title=state.incident_title,
        incident_severity=state.incident_severity,
        workflow_status=state.workflow_status,
        current_step=state.current_step,
        evidence_sufficient=state.evidence_sufficient,
        risk_level=state.risk_level,
        requires_approval=state.requires_approval,
        approved=state.approved,
        remediation_plan=state.remediation_plan,
        executed=state.executed,
        verified=state.verified,
        service_healthy=state.service_healthy,
        error=state.error,
        steps_completed=state.steps_completed,
        mode=state.mode,
        target_agent_id=state.target_agent_id,
        investigation_round=state.investigation_round,
        pending_job_ids=state.pending_job_ids,
        evidence=state.evidence,
        planner_reasoning=state.planner_reasoning,
        remote_action=state.remote_action,
        remote_action_hash=state.remote_action_hash,
    )


def _persist_state(db: Session, state: InvestigationState) -> None:
    """Persist investigation state to the workflow_states table."""
    row = WorkflowState(
        incident_id=state.incident_id,
        tenant_id=state.tenant_id,
        state_json=state.model_dump(),
        status=state.workflow_status,
        current_step=state.current_step,
    )
    db.add(row)
    db.commit()


# A full investigation has a hard Celery limit of 300s. Allow a generous
# margin before treating an in_progress row as abandoned (worker crash).
_IN_PROGRESS_STALE_SECONDS = 600


def _load_latest_state_row(
    db: Session,
    incident_id: int,
    tenant_id: int,
    *,
    for_update: bool = False,
) -> WorkflowState | None:
    query = (
        db.query(WorkflowState)
        .filter(
            WorkflowState.incident_id == incident_id,
            WorkflowState.tenant_id == tenant_id,
        )
        .order_by(WorkflowState.id.desc())
    )
    if for_update:
        query = query.with_for_update()
        query = query.execution_options(populate_existing=True)
    return query.first()


def _is_stale_in_progress(row: WorkflowState) -> bool:
    updated_at = row.updated_at
    if updated_at is None:
        return True
    if updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=timezone.utc)
    age = (datetime.now(timezone.utc) - updated_at).total_seconds()
    return age >= _IN_PROGRESS_STALE_SECONDS


def _new_state(
    incident_id: int,
    tenant_id: int,
    actor_user_id: int | None,
    actor_email: str,
) -> InvestigationState:
    return InvestigationState(
        incident_id=incident_id,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        actor_email=actor_email,
        created_at=datetime.now(timezone.utc).isoformat(),
        updated_at=datetime.now(timezone.utc).isoformat(),
    )


@router.post(
    "/{incident_id}/start",
    response_model=InvestigationStartResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def start_investigation(
    incident_id: int,
    request: Request,
    principal: Principal = Depends(get_current_principal),
    repo: IncidentRepository = Depends(get_incident_repository),
    db: Session = Depends(get_db),
):
    """Start an investigation workflow for an incident.

    Local incidents use the LangGraph shadow-mode workflow. Incidents with an
    active target agent use durable remote jobs instead. Neither executes
    destructive actions without approval. State is persisted to the DB and the
    work runs asynchronously via Celery.

    A second start is rejected while a non-stale run is in progress, and while
    an approved or in-flight remote remediation may still be running. Without
    those guards, a new Celery delivery could be skipped by the advisory lock
    or a stale approval could leak into the new run.
    """
    rate_limit(request)

    incident = repo.get_for_tenant(incident_id, principal.tenant_id)
    if incident is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Incident not found",
        )

    if incident.target_agent_id is not None:
        agent = RemoteAgentService(db).get(
            incident.target_agent_id,
            principal.tenant_id,
        )
        if agent is None or agent.status != RemoteAgentStatus.ACTIVE:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="The incident target agent is not active",
            )

    latest = _load_latest_state_row(
        db,
        incident_id,
        principal.tenant_id,
        for_update=True,
    )
    if (
        latest is not None
        and latest.status == "in_progress"
        and not _is_stale_in_progress(latest)
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "An investigation is already running for this incident. "
                "Wait for it to finish before starting another."
            ),
        )

    job_service = RemoteJobService(db)
    previous_mode = (
        str((latest.state_json or {}).get("mode") or "local")
        if latest is not None
        else "local"
    )
    if (
        incident.target_agent_id is not None or previous_mode == "remote"
    ) and job_service.has_active_remediation(
        principal.tenant_id,
        incident_id,
        for_update=True,
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "A remote remediation may still be running for this incident. "
                "Wait for its result before starting another investigation."
            ),
        )

    if latest is not None:
        state = InvestigationState(**latest.state_json)
    else:
        state = _new_state(
            incident_id=incident_id,
            tenant_id=principal.tenant_id,
            actor_user_id=principal.user_id,
            actor_email=principal.email,
        )

    # Persist a clean initial state before dispatching the async task. A new
    # run must not inherit a previous approval, otherwise it could execute
    # destructive actions without fresh human consent.
    state.actor_user_id = principal.user_id
    state.actor_email = principal.email
    state.run_id = uuid4().hex
    state.workflow_status = "in_progress"
    state.current_step = "load_incident"
    state.error = None
    state.mode = "remote" if incident.target_agent_id is not None else "local"
    state.target_agent_id = incident.target_agent_id

    # Clear every derived field from the previous run. Keeping stale evidence
    # or a stale plan would make a restarted investigation misleading and
    # could carry a previous approval into a new execution attempt.
    state.retrieved_context = ""
    state.retrieved_sources = []
    state.retrieved_distances = []
    state.evidence_sufficient = False
    state.investigation_notes = []
    state.metrics_checked = False
    state.logs_checked = False
    state.deployment_history_checked = False
    state.investigation_round = 0
    state.actions_executed = 0
    state.pending_job_ids = []
    state.evidence = []
    state.planner_reasoning = ""
    state.baseline_metrics = {}
    state.target_service = None
    state.runbook_name = None
    state.remote_action = None
    state.remote_action_hash = None
    state.approval_id = None
    state.remediation_plan = ""
    state.risk_level = "unknown"
    state.requires_approval = False

    state.approved = None
    state.approved_by = None
    state.approved_at = None
    state.approval_reason = ""
    state.executed = False
    state.executed_by = None
    state.executed_at = None
    state.execution_result = ""
    state.execution_error = None
    state.verified = False
    state.verification_result = ""
    state.service_healthy = False
    state.steps_completed = []
    state.updated_at = datetime.now(timezone.utc).isoformat()

    # A new run must not leave an old approval actionable. Cancel only jobs
    # that have not been leased; in-flight work was rejected above. Local-only
    # incidents never touch the remote-job tables.
    if state.mode == "remote" or previous_mode == "remote":
        job_service.cancel_pending_for_incident(
            principal.tenant_id,
            incident_id,
            reason="superseded by a new investigation run",
            commit=False,
        )
    _persist_state(db, state)

    # Dispatch the graph execution or the remote job planner asynchronously.
    try:
        if state.mode == "remote":
            run_remote_investigation.delay(
                incident_id=incident_id,
                actor_user_id=principal.user_id,
                actor_email=principal.email,
                run_id=state.run_id,
            )
        else:
            run_investigation.delay(
                incident_id=incident_id,
                actor_user_id=principal.user_id,
                actor_email=principal.email,
                run_id=state.run_id,
                resume=False,
            )
    except Exception:
        # If Celery dispatch fails, mark the state as failed
        state.workflow_status = "failed"
        state.current_step = "error"
        state.error = "Investigation task could not be dispatched"
        _persist_state(db, state)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Investigation task could not be dispatched. Try again later.",
        )

    return InvestigationStartResponse(
        investigation_id=incident_id,
        workflow_status=state.workflow_status,
        current_step=state.current_step,
    )


@router.get(
    "",
    response_model=list[InvestigationStatusResponse],
)
def list_investigations(
    status_filter: str | None = Query(default=None, alias="status"),
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    """List the latest investigation state per incident, newest first.

    ``?status=waiting_for_approval`` powers the Approvals queue.
    """
    latest_ids = (
        db.query(func.max(WorkflowState.id).label("max_id"))
        .group_by(WorkflowState.incident_id)
        .subquery()
    )
    query = db.query(WorkflowState).join(
        latest_ids,
        WorkflowState.id == latest_ids.c.max_id,
    )
    if not principal.is_superadmin:
        query = query.filter(WorkflowState.tenant_id == principal.tenant_id)
    if status_filter:
        query = query.filter(WorkflowState.status == status_filter)

    rows = query.order_by(WorkflowState.id.desc()).all()
    return [
        _state_to_response(InvestigationState(**row.state_json)) for row in rows
    ]


@router.get(
    "/{incident_id}",
    response_model=InvestigationStatusResponse,
)
def get_investigation(
    incident_id: int,
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    """Get the current state of an investigation workflow."""
    row = (
        db.query(WorkflowState)
        .filter(WorkflowState.incident_id == incident_id)
        .order_by(WorkflowState.id.desc())
        .first()
    )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No investigation found for this incident",
        )

    # Tenant scoping
    if not principal.is_superadmin and row.tenant_id != principal.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to this investigation",
        )

    state = InvestigationState(**row.state_json)
    return _state_to_response(state)


@router.post(
    "/{incident_id}/approve",
    response_model=InvestigationApproveResponse,
)
def approve_investigation(
    incident_id: int,
    http_request: Request,
    request: InvestigationApproveRequest,
    principal: Principal = Depends(require_role(UserRole.RESPONDER)),
    db: Session = Depends(get_db),
):
    """Approve or reject a pending remediation action.

    Only RESPONDER+ can approve. The workflow resumes asynchronously after
    approval via a Celery task. ``FOR UPDATE`` serializes concurrent
    decisions, and only a state that is actually waiting for approval can be
    decided.
    """
    rate_limit(http_request)
    row = (
        db.query(WorkflowState)
        .filter(WorkflowState.incident_id == incident_id)
        .order_by(WorkflowState.id.desc())
        .with_for_update()
        .first()
    )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No investigation found for this incident",
        )

    if not principal.is_superadmin and row.tenant_id != principal.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to this investigation",
        )

    state = InvestigationState(**row.state_json)

    if state.mode == "remote":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Remote remediation is approved per-job. "
                "Use POST /api/v1/remote-jobs/{job_id}/approve."
            ),
        )

    if not state.requires_approval:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This investigation does not require approval",
        )

    if state.approved is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Approval already recorded",
        )

    if state.workflow_status != "waiting_for_approval":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This investigation is not waiting for approval",
        )

    # Record approval/rejection
    state.approved = request.approved
    state.approved_by = principal.user_id
    state.approved_at = datetime.now(timezone.utc).isoformat()
    state.approval_reason = request.reason
    state.updated_at = datetime.now(timezone.utc).isoformat()

    if request.approved:
        # Resume the short approval graph asynchronously. The full analysis
        # and planning graph is deliberately not re-run: the stored plan is
        # the one the human just approved.
        state.run_id = uuid4().hex
        state.workflow_status = "in_progress"
        state.current_step = "execute_approved_action"
        state.error = None
        _persist_state(db, state)

        try:
            run_investigation.delay(
                incident_id=incident_id,
                actor_user_id=principal.user_id,
                actor_email=principal.email,
                run_id=state.run_id,
                resume=True,
            )
        except Exception:
            state.workflow_status = "failed"
            state.current_step = "error"
            state.error = "Investigation task could not be dispatched"
            _persist_state(db, state)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Investigation task could not be dispatched. Try again later.",
            )

        # Audit the approval
        from app.services.audit_log import AuditLogService

        AuditLogService(db).log(
            action="investigation.approve",
            principal=principal,
            resource_type="investigation",
            resource_id=str(incident_id),
            tenant_id=principal.tenant_id,
            details={
                "incident_id": incident_id,
                "approved": True,
                "reason": request.reason,
                "workflow_status": state.workflow_status,
            },
        )

        return InvestigationApproveResponse(
            investigation_id=incident_id,
            approved=True,
            workflow_status=state.workflow_status,
            message="Remediation approved and workflow resumed asynchronously",
        )

    # Rejected — stop the workflow
    state.workflow_status = "completed"
    state.current_step = "end"
    _persist_state(db, state)

    # Audit the rejection
    from app.services.audit_log import AuditLogService

    AuditLogService(db).log(
        action="investigation.reject",
        principal=principal,
        resource_type="investigation",
        resource_id=str(incident_id),
        tenant_id=principal.tenant_id,
        details={
            "incident_id": incident_id,
            "approved": False,
            "reason": request.reason,
        },
    )

    return InvestigationApproveResponse(
        investigation_id=incident_id,
        approved=False,
        workflow_status="completed",
        message="Remediation rejected; workflow stopped",
    )

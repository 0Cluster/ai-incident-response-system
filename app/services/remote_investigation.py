"""Durable remote investigation orchestration.

The workflow is intentionally not one long-running Celery task. A round
creates jobs and exits; agent result processing resumes the investigation,
which either creates another bounded round, proposes remediation, or verifies
recovery.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent.state import InvestigationState
from app.core.auth import Principal
from app.core.config import settings
from app.models.enums import (
    IncidentStatus,
    RemoteAgentStatus,
    RemoteApprovalStatus,
    RemoteExecutionType,
    RemoteJobStatus,
    REMOTE_TERMINAL_STATUSES,
)
from app.models.incident import Incident
from app.models.remote_agent import RemoteAgent
from app.models.remote_job import RemoteJob, RemoteJobApproval, RemoteJobResult
from app.models.runbook import Runbook
from app.models.workflow_state import WorkflowState
from app.remote.actions import (
    list_action_ids,
    validate_action,
)
from app.remote.planner import RemotePlanner
from app.repositories.incident import IncidentRepository
from app.schemas.remote import PlannedAction
from app.services.remote_agent import RemoteAgentService
from app.services.remote_job import (
    RemoteJobExpiredError,
    RemoteJobService,
    make_idempotency_key,
)
from app.services.runbook import RunbookService

logger = logging.getLogger(__name__)


class RemoteInvestigationError(ValueError):
    pass


class RemoteInvestigationNotFoundError(LookupError):
    pass


class RemoteInvestigationConflictError(RemoteInvestigationError):
    pass


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _norm(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


class RemoteInvestigationService:
    def __init__(
        self,
        db: Session,
        *,
        planner: RemotePlanner | None = None,
        jobs: RemoteJobService | None = None,
        agents: RemoteAgentService | None = None,
    ):
        self.db = db
        self.planner = planner or RemotePlanner()
        self.jobs = jobs or RemoteJobService(db)
        self.agents = agents or RemoteAgentService(db)

    # ------------------------------------------------------------------
    # Start
    # ------------------------------------------------------------------

    def start(self, state: InvestigationState) -> InvestigationState:
        incident = IncidentRepository(self.db).get_for_tenant(
            state.incident_id,
            state.tenant_id,
        )
        if incident is None:
            raise RemoteInvestigationNotFoundError(state.incident_id)
        if state.target_agent_id is None:
            state.target_agent_id = incident.target_agent_id
        if state.target_agent_id is None:
            return self._fail(state, "Incident has no target remote agent")

        agent = self.agents.get(state.target_agent_id, state.tenant_id)
        if agent is None:
            return self._fail(state, "Target remote agent not found")
        if agent.status != RemoteAgentStatus.ACTIVE:
            return self._fail(state, "Target remote agent is not active")

        runbook, context, allowed_actions, service = self._load_runbook(
            incident,
            state.tenant_id,
        )
        state.mode = "remote"
        state.target_agent_id = agent.id
        state.runbook_name = runbook.name if runbook else None
        state.target_service = service
        state.retrieved_context = context
        state.retrieved_sources = [runbook.name] if runbook else []
        state.investigation_round = 1
        state.actions_executed = 0
        state.max_rounds = settings.REMOTE_MAX_INVESTIGATION_ROUNDS
        state.max_actions = settings.REMOTE_MAX_TOTAL_ACTIONS
        state.evidence = []
        state.pending_job_ids = []
        state.baseline_metrics = {}
        state.remote_action = None
        state.remote_action_hash = None
        state.approval_id = None
        state.approved = None
        state.approved_by = None
        state.approved_at = None
        state.approval_reason = ""
        state.executed = False
        state.executed_at = None
        state.execution_result = ""
        state.execution_error = None
        state.verified = False
        state.verification_result = ""
        state.service_healthy = False
        state.error = None
        state.workflow_status = "in_progress"
        state.current_step = "plan_investigation"

        plan = self.planner.plan(
            incident_title=incident.title,
            incident_message=incident.message,
            runbook_context=context,
            evidence=[],
            allowed_actions=allowed_actions,
            agent_capabilities=agent.capabilities or [],
            round_number=1,
            max_actions=settings.REMOTE_MAX_ACTIONS_PER_ROUND,
        )
        state.planner_reasoning = plan.reasoning_summary
        state.remediation_plan = (
            f"Objective: {plan.objective}\n\n{plan.reasoning_summary}"
        )
        created = self._create_jobs(
            state=state,
            actions=plan.actions,
            execution_type=RemoteExecutionType.DIAGNOSTIC,
            allowed_actions=allowed_actions,
            agent=agent,
            requires_approval=False,
            round_number=1,
        )
        if not created:
            self._finish_human_review(
                state,
                "No allowed diagnostic actions are available for this agent.",
            )
            self._persist_state(state)
            return state

        state.pending_job_ids = [job.id for job in created]
        state.current_step = "await_remote_results"
        state.workflow_status = "waiting_for_agent"
        self._set_incident_status(incident, IncidentStatus.ACKNOWLEDGED)
        self._persist_state(state)
        return state

    # ------------------------------------------------------------------
    # Result processing
    # ------------------------------------------------------------------

    def process_job_result(self, job_id: int) -> None:
        job = self.db.get(RemoteJob, job_id)
        if job is None or job.result_processed_at is not None:
            return

        # Lock order is workflow state, then job. The start/approval endpoints
        # use the same order, so a concurrent restart cannot interleave a new
        # run with a result from the old one.
        row, state = self._latest_state(
            job.incident_id,
            job.tenant_id,
            for_update=True,
        )
        statement = select(RemoteJob).where(RemoteJob.id == job_id)
        bind = self.db.get_bind()
        if bind is not None and bind.dialect.name == "postgresql":
            # The outbox worker and the recovery backstop may race. Lock the
            # job row so only one of them advances the investigation.
            statement = statement.with_for_update()
            statement = statement.execution_options(populate_existing=True)
        job = self.db.scalar(statement)
        if job is None or job.result_processed_at is not None:
            return
        result = self.db.scalar(
            select(RemoteJobResult).where(RemoteJobResult.job_id == job.id)
        )
        if result is None:
            # A job can expire or be declared UNKNOWN without an agent result.
            # Advance the investigation so it cannot wait forever.
            if (
                job.status in REMOTE_TERMINAL_STATUSES
                and job.result_processed_at is None
            ):
                self._process_terminal_without_result(job)
            return

        if row is None or state is None:
            self._mark_processed(job)
            return
        if state.mode != "remote" or state.run_id != job.investigation_run_id:
            # The result is retained for audit, but a superseded run must not
            # advance the current investigation.
            self._mark_processed(job)
            return
        if job.id not in state.pending_job_ids:
            self._mark_processed(job)
            return

        self._append_evidence(state, job, result)
        state.pending_job_ids = [
            pending for pending in state.pending_job_ids if pending != job.id
        ]

        if state.pending_job_ids:
            self._persist_state(state)
            self._mark_processed(job)
            return

        incident = IncidentRepository(self.db).get_for_tenant(
            job.incident_id,
            job.tenant_id,
        )
        if incident is None:
            self._mark_processed(job)
            return

        if job.execution_type == RemoteExecutionType.DIAGNOSTIC:
            self._after_diagnostics(state, incident, job)
        elif job.execution_type == RemoteExecutionType.REMEDIATION:
            self._after_remediation(state, incident, job)
        elif job.execution_type == RemoteExecutionType.VERIFICATION:
            self._after_verification(state, incident, job, result)

        self._mark_processed(job)

    def _process_terminal_without_result(self, job: RemoteJob) -> None:
        """Advance a run when a job expires or becomes UNKNOWN without a result.

        Without this, a revoked agent, expired approval, or crash-lost lease
        would leave the investigation in ``waiting_for_agent`` forever.
        """
        row, state = self._latest_state(job.incident_id, job.tenant_id)
        if row is None or state is None:
            self._mark_processed(job)
            return
        if state.mode != "remote" or state.run_id != job.investigation_run_id:
            self._mark_processed(job)
            return
        if job.id not in state.pending_job_ids:
            self._mark_processed(job)
            return

        if job.execution_type == RemoteExecutionType.REMEDIATION:
            if job.status == RemoteJobStatus.UNKNOWN:
                message = (
                    "Remote remediation outcome is UNKNOWN after an agent or "
                    "lease failure. AIRS will not replay it; reconcile the host "
                    "manually."
                )
                state.executed = True
            elif job.status == RemoteJobStatus.EXPIRED:
                message = "Remote remediation approval expired before execution."
            else:
                message = (
                    "Remote remediation ended without a result "
                    f"({job.status.value})."
                )
            state.execution_error = message
        else:
            message = (
                f"Remote {job.execution_type.value} job #{job.id} ended "
                f"without a result ({job.status.value})."
            )

        state.evidence = (
            state.evidence
            + [
                {
                    "job_id": job.id,
                    "action_id": job.action_id,
                    "parameters": job.action_parameters or {},
                    "execution_type": job.execution_type.value,
                    "status": job.status.value,
                    "exit_code": None,
                    "duration_ms": None,
                    "output": {"error": message},
                }
            ]
        )[-20:]
        state.pending_job_ids = [
            pending for pending in state.pending_job_ids if pending != job.id
        ]
        if state.pending_job_ids:
            self._persist_state(state)
            self._mark_processed(job)
            return

        state.workflow_status = "failed"
        state.current_step = "error"
        state.error = message
        state.verified = False
        state.service_healthy = False
        self._persist_state(state)
        self._mark_processed(job)

    def _after_diagnostics(
        self,
        state: InvestigationState,
        incident: Incident,
        job: RemoteJob,
    ) -> None:
        if state.investigation_round >= state.max_rounds:
            self._finish_human_review(
                state,
                "Investigation reached its round limit without a safe remediation proposal.",
            )
            self._persist_state(state)
            return

        agent = self.agents.get(state.target_agent_id or 0, state.tenant_id)
        if agent is None or agent.status != RemoteAgentStatus.ACTIVE:
            self._fail(state, "Target remote agent is no longer active")
            self._persist_state(state)
            return

        allowed = self._allowed_actions(state)
        plan = self.planner.plan(
            incident_title=incident.title,
            incident_message=incident.message,
            runbook_context=state.retrieved_context,
            evidence=state.evidence,
            allowed_actions=allowed,
            agent_capabilities=agent.capabilities or [],
            round_number=state.investigation_round + 1,
            max_actions=settings.REMOTE_MAX_ACTIONS_PER_ROUND,
        )
        state.planner_reasoning = plan.reasoning_summary
        if plan.actions:
            next_round = state.investigation_round + 1
            created = self._create_jobs(
                state=state,
                actions=plan.actions,
                execution_type=RemoteExecutionType.DIAGNOSTIC,
                allowed_actions=allowed,
                agent=agent,
                requires_approval=False,
                round_number=next_round,
            )
            if created:
                state.investigation_round = next_round
                state.pending_job_ids = [item.id for item in created]
                state.current_step = "await_remote_results"
                state.workflow_status = "waiting_for_agent"
                self._persist_state(state)
                return

        self._propose_remediation(state, incident)

    def _after_remediation(
        self,
        state: InvestigationState,
        incident: Incident,
        job: RemoteJob,
    ) -> None:
        state.executed = True
        state.executed_at = _utcnow().isoformat()
        if job.status == RemoteJobStatus.SUCCEEDED:
            state.execution_result = "Remote remediation completed successfully."
        else:
            state.execution_error = job.last_error or (
                f"Remote remediation ended with {job.status.value}."
            )

        agent = self.agents.get(state.target_agent_id or 0, state.tenant_id)
        if agent is None or agent.status != RemoteAgentStatus.ACTIVE:
            self._fail(state, "Target remote agent disappeared during remediation")
            self._persist_state(state)
            return

        actions = [
            PlannedAction(
                action_id="inspect_memory",
                parameters={},
                purpose="Verify memory pressure after remediation",
            )
        ]
        if state.target_service:
            actions.append(
                PlannedAction(
                    action_id="inspect_service_status",
                    parameters={"service": state.target_service},
                    purpose="Verify the affected service is active",
                )
            )
        created = self._create_jobs(
            state=state,
            actions=actions,
            execution_type=RemoteExecutionType.VERIFICATION,
            allowed_actions=set(list_action_ids()),
            agent=agent,
            requires_approval=False,
            round_number=state.investigation_round + 1,
        )
        if not created:
            self._finish_human_review(
                state,
                "Remediation ran but no verification action could be queued.",
            )
            self._persist_state(state)
            return

        state.investigation_round += 1
        state.pending_job_ids = [item.id for item in created]
        state.current_step = "await_verification"
        state.workflow_status = "waiting_for_agent"
        self._persist_state(state)

    def _after_verification(
        self,
        state: InvestigationState,
        incident: Incident,
        job: RemoteJob,
        result: RemoteJobResult,
    ) -> None:
        passed = self._verification_overall_passed(state)
        state.verified = True
        state.service_healthy = passed
        state.verification_result = (
            "Recovery verified by remote evidence."
            if passed
            else "Verification did not confirm recovery; human review required."
        )
        state.current_step = "end"
        state.workflow_status = "completed"
        if passed:
            self._set_incident_status(incident, IncidentStatus.RESOLVED)
        else:
            self._set_incident_status(incident, IncidentStatus.ACKNOWLEDGED)
        self._persist_state(state)

    # ------------------------------------------------------------------
    # Remediation proposal and approval
    # ------------------------------------------------------------------

    def _propose_remediation(
        self,
        state: InvestigationState,
        incident: Incident,
    ) -> None:
        if state.actions_executed >= state.max_actions:
            self._finish_human_review(
                state,
                "Action budget exhausted before a remediation proposal.",
            )
            self._persist_state(state)
            return

        candidate = self._remediation_candidate(state)
        if candidate is None:
            self._finish_human_review(
                state,
                "Insufficient evidence for a safe remediation proposal.",
            )
            self._persist_state(state)
            return

        action_id, parameters, reason = candidate
        if action_id not in self._remediation_allowed_actions(state):
            self._finish_human_review(
                state,
                f"Runbook does not allow remediation action {action_id}.",
            )
            self._persist_state(state)
            return

        agent = self.agents.get(state.target_agent_id or 0, state.tenant_id)
        if agent is None:
            self._fail(state, "Target remote agent not found")
            self._persist_state(state)
            return

        try:
            remediation_job = self.jobs.create_job(
                tenant_id=state.tenant_id,
                incident_id=state.incident_id,
                agent_id=agent.id,
                action_id=action_id,
                parameters=parameters,
                execution_type=RemoteExecutionType.REMEDIATION,
                run_id=state.run_id,
                round_number=state.investigation_round + 1,
                description=reason,
                requested_by=state.actor_user_id,
                commit=False,
            )
        except Exception as exc:  # noqa: BLE001
            self._fail(state, f"Could not create remediation job: {exc}")
            self._persist_state(state)
            return

        state.actions_executed += 1
        approval = self.db.scalar(
            select(RemoteJobApproval).where(
                RemoteJobApproval.job_id == remediation_job.id
            )
        )
        state.remote_action = {
            "job_id": remediation_job.id,
            "action_id": action_id,
            "parameters": parameters,
            "description": reason,
            "risk_level": remediation_job.risk_level,
        }
        state.remote_action_hash = approval.action_hash if approval else None
        state.approval_id = approval.id if approval else None
        state.risk_level = remediation_job.risk_level
        state.requires_approval = True
        state.approved = None
        state.remediation_plan = (
            f"Proposed remediation: {action_id}\n"
            f"Parameters: {parameters}\n\n{reason}\n\n"
            "Approval is bound to the exact target, action, and parameters."
        )
        state.pending_job_ids = [remediation_job.id]
        state.current_step = "wait_for_approval"
        state.workflow_status = "waiting_for_approval"
        self._set_incident_status(incident, IncidentStatus.ACKNOWLEDGED)
        self._persist_state(state)

    def approve(
        self,
        *,
        job_id: int,
        principal: Principal,
        approved: bool,
        reason: str = "",
        provided_action_hash: str | None = None,
    ) -> RemoteJob:
        job = self.jobs.require_for_tenant(job_id, principal.tenant_id)
        row, state = self._latest_state(
            job.incident_id,
            job.tenant_id,
            for_update=True,
        )
        if row is None or state is None:
            raise RemoteInvestigationNotFoundError(job.incident_id)
        # Lock order is workflow state, then job, matching result processing.
        job = self.jobs.require_for_tenant(
            job_id,
            principal.tenant_id,
            for_update=True,
        )
        if job.status != RemoteJobStatus.PENDING_APPROVAL:
            raise RemoteInvestigationConflictError(
                f"Job is {job.status.value}, not awaiting approval."
            )
        if state.mode != "remote" or state.run_id != job.investigation_run_id:
            raise RemoteInvestigationConflictError(
                "This job belongs to a superseded investigation run."
            )
        approval = self.db.scalar(
            select(RemoteJobApproval).where(RemoteJobApproval.job_id == job.id)
        )
        if approval is None:
            raise RemoteInvestigationConflictError("Approval record is missing.")

        expected = self.jobs.compute_action_hash(job)
        if approval.action_hash != expected:
            raise RemoteInvestigationConflictError(
                "Job parameters changed since approval was proposed."
            )
        if provided_action_hash and provided_action_hash != expected:
            raise RemoteInvestigationConflictError(
                "Approval does not match the current job action."
            )
        expires_at = _norm(approval.expires_at)
        if expires_at is not None and expires_at <= _utcnow():
            approval.status = RemoteApprovalStatus.EXPIRED
            job.status = RemoteJobStatus.EXPIRED
            job.completed_at = _utcnow()
            job.last_error = "approval expired"
            self.db.commit()
            # Reflect the expiry immediately instead of waiting for the
            # 30-second recovery task.
            self.process_job_result(job.id)
            raise RemoteJobExpiredError("Approval has expired.")

        now = _utcnow()
        approval.reason = reason
        approval.approved_by = principal.user_id
        approval.approved_by_email = principal.email
        if approved:
            approval.status = RemoteApprovalStatus.APPROVED
            approval.approved_at = now
            job.status = RemoteJobStatus.APPROVED
            job.approved_at = now
            state.approved = True
            state.approved_by = principal.user_id
            state.approved_at = now.isoformat()
            state.approval_reason = reason
            state.current_step = "await_remediation"
            state.workflow_status = "waiting_for_agent"
            event_type = "job.approved"
        else:
            approval.status = RemoteApprovalStatus.REJECTED
            approval.approved_at = now
            job.status = RemoteJobStatus.CANCELLED
            job.completed_at = now
            job.last_error = "rejected by operator"
            state.approved = False
            state.approved_by = principal.user_id
            state.approved_at = now.isoformat()
            state.approval_reason = reason
            state.current_step = "end"
            state.workflow_status = "completed"
            state.executed = False
            state.execution_error = "Remediation rejected by operator"
            state.pending_job_ids = []
            job.result_processed_at = now
            event_type = "job.rejected"

        self.jobs._event(job, event_type, actor_type="user", actor_id=principal.user_id)
        self._persist_state(state)
        return job

    # ------------------------------------------------------------------
    # Job creation
    # ------------------------------------------------------------------

    def _create_jobs(
        self,
        *,
        state: InvestigationState,
        actions: list[PlannedAction],
        execution_type: RemoteExecutionType,
        allowed_actions: set[str],
        agent: RemoteAgent,
        requires_approval: bool,
        round_number: int,
    ) -> list[RemoteJob]:
        created: list[RemoteJob] = []
        remaining = max(0, state.max_actions - state.actions_executed)
        limit = min(
            settings.REMOTE_MAX_ACTIONS_PER_ROUND,
            remaining,
        )
        seen: set[tuple[str, str]] = set()
        for planned in actions[:limit]:
            if planned.action_id not in allowed_actions:
                continue
            if agent.capabilities and planned.action_id not in agent.capabilities:
                continue
            try:
                definition, normalized = validate_action(
                    planned.action_id,
                    planned.parameters,
                )
            except ValueError:
                continue
            compatible_type = (
                definition.execution_type == execution_type
                or (
                    execution_type == RemoteExecutionType.VERIFICATION
                    and definition.execution_type == RemoteExecutionType.DIAGNOSTIC
                )
            )
            if not compatible_type:
                continue
            marker = (
                planned.action_id,
                make_idempotency_key(
                    incident_id=state.incident_id,
                    run_id=state.run_id,
                    round_number=round_number,
                    action_id=planned.action_id,
                    parameters=normalized,
                ),
            )
            if marker in seen:
                continue
            seen.add(marker)
            job = self.jobs.create_job(
                tenant_id=state.tenant_id,
                incident_id=state.incident_id,
                agent_id=agent.id,
                action_id=planned.action_id,
                parameters=normalized,
                execution_type=execution_type,
                run_id=state.run_id,
                round_number=round_number,
                description=planned.purpose or None,
                requested_by=state.actor_user_id,
                requires_approval=requires_approval,
                commit=False,
            )
            created.append(job)
        state.actions_executed += len(created)
        return created

    # ------------------------------------------------------------------
    # Evidence and verification
    # ------------------------------------------------------------------

    def _append_evidence(
        self,
        state: InvestigationState,
        job: RemoteJob,
        result: RemoteJobResult,
    ) -> None:
        output = result.structured_output
        compact_output: Any = output
        if compact_output is None:
            compact_output = {
                "stdout": (result.stdout_redacted or "")[:6000],
                "stderr": (result.stderr_redacted or "")[:2000],
            }
        item = {
            "job_id": job.id,
            "action_id": job.action_id,
            "parameters": job.action_parameters or {},
            "execution_type": job.execution_type.value,
            "status": result.status.value,
            "exit_code": result.exit_code,
            "duration_ms": result.duration_ms,
            "output": compact_output,
        }
        state.evidence = (state.evidence + [item])[-20:]
        if (
            job.action_id == "inspect_memory"
            and job.execution_type == RemoteExecutionType.DIAGNOSTIC
            and isinstance(compact_output, dict)
            and compact_output.get("used_percent") is not None
        ):
            state.baseline_metrics = {
                "memory_used_percent": compact_output.get("used_percent"),
                "captured_at": _utcnow().isoformat(),
            }

    def _verification_overall_passed(self, state: InvestigationState) -> bool:
        items = [
            item
            for item in state.evidence
            if item.get("execution_type") == RemoteExecutionType.VERIFICATION.value
        ]
        if not items:
            return False
        for item in items:
            if item.get("status") != RemoteJobStatus.SUCCEEDED.value:
                return False
            output = item.get("output") or {}
            if item.get("action_id") == "inspect_memory":
                used = output.get("used_percent")
                if used is None:
                    return False
                baseline = state.baseline_metrics.get("memory_used_percent")
                threshold = settings.REMOTE_VERIFICATION_MEMORY_PERCENT
                drop = settings.REMOTE_VERIFICATION_MEMORY_DROP
                under_threshold = float(used) <= threshold
                dropped = (
                    baseline is not None
                    and float(used) <= float(baseline) - drop
                )
                if not (under_threshold or dropped):
                    return False
            elif item.get("action_id") == "inspect_service_status":
                if not bool(output.get("active")):
                    return False
        return True

    def _remediation_candidate(
        self,
        state: InvestigationState,
    ) -> tuple[str, dict[str, Any], str] | None:
        # Prefer terminating the one process that was actually inspected.
        inspected: dict[int, dict[str, Any]] = {}
        top_processes: dict[int, dict[str, Any]] = {}
        for item in state.evidence:
            output = item.get("output") or {}
            if not isinstance(output, dict):
                continue
            if item.get("action_id") == "inspect_process" and output.get("pid"):
                inspected[int(output["pid"])] = output
            if item.get("action_id") == "list_memory_processes":
                for process in output.get("processes") or []:
                    if isinstance(process, dict) and process.get("pid"):
                        top_processes[int(process["pid"])] = process

        for pid, process in inspected.items():
            if pid not in top_processes:
                continue
            user = str(process.get("user") or "")
            command = str(process.get("command") or "")
            if user in ("root", "systemd", "kernel") or any(
                critical in command
                for critical in ("systemd", "sshd", "init", "kernel")
            ):
                continue
            return (
                "terminate_process",
                {
                    "pid": pid,
                    "start_time": process.get("start_time"),
                    "user": user or None,
                    "command": command or None,
                },
                (
                    f"PID {pid} ({command or 'unknown command'}) owns the largest "
                    "memory footprint and was re-inspected. Terminate it only "
                    "after operator approval."
                ),
            )

        if state.target_service:
            return (
                "restart_service",
                {"service": state.target_service},
                (
                    f"The runbook identifies {state.target_service} as the "
                    "affected service. Restart it only after operator approval."
                ),
            )
        return None

    # ------------------------------------------------------------------
    # Persistence and helpers
    # ------------------------------------------------------------------

    def _latest_state(
        self,
        incident_id: int,
        tenant_id: int,
        *,
        for_update: bool = False,
    ) -> tuple[WorkflowState | None, InvestigationState | None]:
        statement = (
            select(WorkflowState)
            .where(
                WorkflowState.incident_id == incident_id,
                WorkflowState.tenant_id == tenant_id,
            )
            .order_by(WorkflowState.id.desc())
            .limit(1)
        )
        if for_update:
            bind = self.db.get_bind()
            if bind is not None and bind.dialect.name == "postgresql":
                statement = statement.with_for_update()
            statement = statement.execution_options(populate_existing=True)
        row = self.db.scalar(statement)
        if row is None:
            return None, None
        return row, InvestigationState(**row.state_json)

    def _persist_state(self, state: InvestigationState) -> None:
        state.updated_at = _utcnow().isoformat()
        self.db.add(
            WorkflowState(
                incident_id=state.incident_id,
                tenant_id=state.tenant_id,
                state_json=state.model_dump(),
                status=state.workflow_status,
                current_step=state.current_step,
            )
        )
        self.db.commit()

    def _mark_processed(self, job: RemoteJob) -> None:
        job.result_processed_at = _utcnow()
        self.db.commit()

    def _set_incident_status(
        self,
        incident: Incident,
        status: IncidentStatus,
    ) -> None:
        if incident.status in (IncidentStatus.CLOSED, IncidentStatus.RESOLVED):
            return
        incident.status = status
        self.db.commit()

    def _fail(self, state: InvestigationState, message: str) -> InvestigationState:
        state.workflow_status = "failed"
        state.current_step = "error"
        state.error = message
        self._persist_state(state)
        return state

    def _finish_human_review(
        self,
        state: InvestigationState,
        message: str,
    ) -> InvestigationState:
        state.workflow_status = "completed"
        state.current_step = "end"
        state.investigation_notes = (state.investigation_notes + [message])[-20:]
        state.remediation_plan = (
            (state.remediation_plan + "\n\n" if state.remediation_plan else "")
            + message
        )
        return state

    def _load_runbook(
        self,
        incident: Incident,
        tenant_id: int,
    ) -> tuple[Runbook | None, str, set[str], str | None]:
        runbooks = RunbookService(self.db).list(tenant_id)
        text = f"{incident.title} {incident.message}".lower()
        selected: Runbook | None = None
        for runbook in runbooks:
            metadata = runbook.metadata_json or {}
            alert_types = [
                str(value).lower()
                for value in metadata.get("alert_types", [])
            ]
            if runbook.name.lower() in text:
                selected = runbook
                break
            if any(value and value in text for value in alert_types):
                selected = runbook
                break
        if selected is None:
            for runbook in runbooks:
                if runbook.name.lower().split("-")[0] in text:
                    selected = runbook
                    break

        metadata = (selected.metadata_json or {}) if selected else {}
        investigation = metadata.get("investigation_actions")
        allowed = set(investigation) if investigation else set(list_action_ids())
        allowed |= {"inspect_memory", "list_memory_processes", "inspect_process"}
        allowed -= {"restart_service", "terminate_process"}
        service = metadata.get("service")
        context = selected.content if selected else ""
        return selected, context, allowed, service

    def _allowed_actions(self, state: InvestigationState) -> set[str]:
        if state.runbook_name:
            runbook = RunbookService(self.db).get(
                state.runbook_name,
                state.tenant_id,
            )
            if runbook is not None:
                metadata = runbook.metadata_json or {}
                configured = metadata.get("investigation_actions")
                if configured:
                    return set(configured)
        return set(list_action_ids()) - {"restart_service", "terminate_process"}

    def _remediation_allowed_actions(self, state: InvestigationState) -> set[str]:
        if state.runbook_name:
            runbook = RunbookService(self.db).get(
                state.runbook_name,
                state.tenant_id,
            )
            if runbook is not None:
                metadata = runbook.metadata_json or {}
                configured = metadata.get("remediation_actions")
                if configured:
                    return set(configured)
        return {"restart_service", "terminate_process"}

"""Durable remote job lifecycle: creation, leasing, acknowledgement, results.

Delivery is at-least-once. A completed job is never executed twice by AIRS:
the unique result row and the agent-side execution store absorb duplicates.
"""

from __future__ import annotations

import json
import secrets
import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.enums import (
    RemoteApprovalStatus,
    RemoteExecutionType,
    RemoteJobStatus,
    REMOTE_TERMINAL_STATUSES,
)
from app.models.remote_job import (
    RemoteJob,
    RemoteJobApproval,
    RemoteJobEvent,
    RemoteJobResult,
)
from app.models.outbox import OutboxEvent
from app.repositories.outbox import OutboxRepository
from app.remote.actions import validate_action
from app.remote.security import (
    action_hash as compute_action_hash,
    clean_output,
    is_expired,
    parameters_hash as compute_parameters_hash,
    redact_text,
    sanitize_structured,
    utcnow,
)
from app.schemas.remote import JobResultRequest


class RemoteJobError(ValueError):
    pass


class RemoteJobNotFoundError(LookupError):
    pass


class RemoteJobConflictError(RemoteJobError):
    pass


class RemoteJobExpiredError(RemoteJobError):
    pass


class RemoteJobLeaseError(RemoteJobError):
    pass


RESULT_STATUSES = {
    RemoteJobStatus.SUCCEEDED,
    RemoteJobStatus.FAILED,
    RemoteJobStatus.TIMED_OUT,
    RemoteJobStatus.UNKNOWN,
}


def make_idempotency_key(
    *,
    incident_id: int,
    run_id: str | None,
    round_number: int,
    action_id: str,
    parameters: dict[str, Any],
) -> str:
    token = compute_parameters_hash(parameters)
    raw = (
        f"remote:{incident_id}:{run_id or 'manual'}:"
        f"{round_number}:{action_id}:{token}"
    )
    if len(raw) <= 255:
        return raw
    return f"remote:{compute_parameters_hash({'raw': raw})}"


class RemoteJobService:
    def __init__(self, db: Session):
        self.db = db

    # ------------------------------------------------------------------
    # Creation
    # ------------------------------------------------------------------

    def create_job(
        self,
        *,
        tenant_id: int,
        incident_id: int,
        agent_id: int,
        action_id: str,
        parameters: dict[str, Any] | None = None,
        execution_type: RemoteExecutionType,
        run_id: str | None,
        round_number: int = 1,
        risk_level: str | None = None,
        requires_approval: bool | None = None,
        description: str | None = None,
        requested_by: int | None = None,
        timeout_seconds: int | None = None,
        ttl_seconds: int | None = None,
        commit: bool = False,
    ) -> RemoteJob:
        definition, normalized = validate_action(action_id, parameters or {})
        # Verification reuses the diagnostic probes (for example,
        # inspect_memory) under a distinct execution type.
        compatible_type = (
            definition.execution_type == execution_type
            or (
                execution_type == RemoteExecutionType.VERIFICATION
                and definition.execution_type == RemoteExecutionType.DIAGNOSTIC
            )
        )
        if not compatible_type:
            raise RemoteJobError(
                f"{action_id} is a {definition.execution_type.value} action, "
                f"not {execution_type.value}"
            )

        if risk_level is None:
            risk_level = definition.risk_level
        if requires_approval is None:
            requires_approval = definition.requires_approval

        status = (
            RemoteJobStatus.PENDING_APPROVAL
            if requires_approval
            else RemoteJobStatus.APPROVED
        )
        key = make_idempotency_key(
            incident_id=incident_id,
            run_id=run_id,
            round_number=round_number,
            action_id=action_id,
            parameters=normalized,
        )
        existing = self.db.scalar(
            select(RemoteJob).where(RemoteJob.idempotency_key == key)
        )
        if existing is not None:
            return existing

        now = utcnow()
        job = RemoteJob(
            tenant_id=tenant_id,
            incident_id=incident_id,
            agent_id=agent_id,
            investigation_run_id=run_id,
            round_number=round_number,
            action_id=action_id,
            action_parameters=normalized,
            execution_type=execution_type,
            risk_level=risk_level,
            status=status,
            idempotency_key=key,
            timeout_seconds=timeout_seconds or definition.timeout_seconds,
            requested_by=requested_by,
            description=description,
            expires_at=now
            + timedelta(
                seconds=(
                    ttl_seconds
                    if ttl_seconds is not None
                    else settings.REMOTE_JOB_DEFAULT_TTL_SECONDS
                )
            ),
        )
        self.db.add(job)
        self.db.flush()

        if requires_approval:
            approval = RemoteJobApproval(
                tenant_id=tenant_id,
                job_id=job.id,
                incident_id=incident_id,
                status=RemoteApprovalStatus.PENDING,
                action_hash=compute_action_hash(
                    tenant_id=tenant_id,
                    incident_id=incident_id,
                    agent_id=agent_id,
                    action_id=action_id,
                    parameters=normalized,
                    risk_level=risk_level,
                ),
                parameters_hash=compute_parameters_hash(normalized),
                risk_level=risk_level,
                expires_at=job.expires_at,
            )
            self.db.add(approval)

        self._event(
            job,
            "job.created",
            details={
                "action_id": action_id,
                "parameters": normalized,
                "execution_type": execution_type.value,
                "status": status.value,
            },
        )
        if commit:
            self.db.commit()
            self.db.refresh(job)
        else:
            self.db.flush()
        return job

    # ------------------------------------------------------------------
    # Agent operations
    # ------------------------------------------------------------------

    def _active_job_query(
        self,
        *,
        tenant_id: int,
        agent_id: int,
    ) -> Select:
        return select(RemoteJob).where(
            RemoteJob.tenant_id == tenant_id,
            RemoteJob.agent_id == agent_id,
        )

    def lease_next(
        self,
        *,
        tenant_id: int,
        agent_id: int,
    ) -> RemoteJob | None:
        """Atomically lease one approved, unexpired job to an agent."""
        self.recover_expired_leases()
        now = utcnow()
        statement = (
            self._active_job_query(tenant_id=tenant_id, agent_id=agent_id)
            .where(
                RemoteJob.status == RemoteJobStatus.APPROVED,
                RemoteJob.expires_at > now,
            )
            .order_by(RemoteJob.created_at, RemoteJob.id)
            .limit(1)
        )
        bind = self.db.get_bind()
        if bind is not None and bind.dialect.name == "postgresql":
            statement = statement.with_for_update(skip_locked=True)

        job = self.db.scalar(statement)
        if job is None:
            return None

        lease_id = secrets.token_urlsafe(24)
        job.status = RemoteJobStatus.DISPATCHED
        job.lease_id = lease_id
        job.lease_expires_at = now + timedelta(
            seconds=job.timeout_seconds + 30
        )
        job.dispatched_at = now
        job.attempt_count = (job.attempt_count or 0) + 1
        job.last_error = None
        self._event(
            job,
            "job.dispatched",
            details={"lease_id": lease_id, "attempt": job.attempt_count},
        )
        self.db.commit()
        self.db.refresh(job)
        return job

    def acknowledge(
        self,
        *,
        tenant_id: int,
        agent_id: int,
        job_id: int,
        lease_id: str,
    ) -> RemoteJob:
        job = self._get_agent_job(
            tenant_id=tenant_id,
            agent_id=agent_id,
            job_id=job_id,
            for_update=True,
        )
        if job.lease_id != lease_id:
            raise RemoteJobLeaseError("job lease does not match")
        if (
            job.status
            in (
                RemoteJobStatus.DISPATCHED,
                RemoteJobStatus.ACKNOWLEDGED,
                RemoteJobStatus.RUNNING,
            )
            and is_expired(job.lease_expires_at)
        ):
            raise RemoteJobExpiredError("job lease has expired")
        if job.status == RemoteJobStatus.DISPATCHED:
            job.status = RemoteJobStatus.ACKNOWLEDGED
            job.started_at = utcnow()
            self._event(job, "job.acknowledged")
            self.db.commit()
            self.db.refresh(job)
        elif job.status in (
            RemoteJobStatus.ACKNOWLEDGED,
            RemoteJobStatus.RUNNING,
        ):
            # Duplicate acknowledgement is harmless.
            pass
        elif job.status in REMOTE_TERMINAL_STATUSES:
            raise RemoteJobConflictError("job is already complete")
        else:
            raise RemoteJobConflictError(
                f"job cannot be acknowledged in status {job.status.value}"
            )
        return job

    def submit_result(
        self,
        *,
        tenant_id: int,
        agent_id: int,
        job_id: int,
        data: JobResultRequest,
    ) -> RemoteJobResult:
        job = self._get_agent_job(
            tenant_id=tenant_id,
            agent_id=agent_id,
            job_id=job_id,
            for_update=True,
        )
        if job.lease_id != data.lease_id:
            raise RemoteJobLeaseError("job lease does not match")

        existing = self.db.scalar(
            select(RemoteJobResult).where(RemoteJobResult.job_id == job.id)
        )
        if existing is not None:
            # At-least-once delivery: return the stored result, never execute
            # or persist a second outcome.
            return existing

        if job.status in (
            RemoteJobStatus.EXPIRED,
            RemoteJobStatus.CANCELLED,
        ):
            raise RemoteJobConflictError(
                f"job is {job.status.value}; result rejected"
            )
        if job.status in REMOTE_TERMINAL_STATUSES:
            raise RemoteJobConflictError("job already has a terminal state")

        try:
            result_status = RemoteJobStatus(data.status.upper())
        except ValueError as exc:
            raise RemoteJobError(
                "result status must be SUCCEEDED, FAILED, TIMED_OUT, or UNKNOWN"
            ) from exc
        if result_status not in RESULT_STATUSES:
            raise RemoteJobError(
                "result status must be SUCCEEDED, FAILED, TIMED_OUT, or UNKNOWN"
            )

        limit = 131_072
        now = utcnow()
        structured_output = (
            sanitize_structured(data.structured_output, limit=limit)
            if data.structured_output is not None
            else None
        )
        if structured_output is not None:
            encoded = json.dumps(structured_output, default=str).encode("utf-8")
            if len(encoded) > limit * 2:
                structured_output = {
                    "truncated": True,
                    "reason": "structured output exceeded transport limit",
                }
        result = RemoteJobResult(
            job_id=job.id,
            tenant_id=tenant_id,
            agent_id=agent_id,
            status=result_status,
            exit_code=data.exit_code,
            stdout_redacted=clean_output(data.stdout, limit=limit),
            stderr_redacted=clean_output(data.stderr, limit=limit),
            structured_output=structured_output,
            error_message=redact_text(data.error_message),
            started_at=data.started_at,
            completed_at=data.completed_at or now,
            duration_ms=data.duration_ms,
        )
        self.db.add(result)

        job.status = result_status
        job.completed_at = result.completed_at
        job.last_error = redact_text(data.error_message)
        job.lease_expires_at = None
        self._event(
            job,
            "job.result_received",
            details={
                "status": result_status.value,
                "exit_code": data.exit_code,
                "duration_ms": data.duration_ms,
            },
        )
        self.db.flush()

        event_key = f"remote_result:{job.id}"
        if self.db.scalar(
            select(OutboxEvent).where(
                OutboxEvent.idempotency_key == event_key
            )
        ) is None:
            OutboxRepository(self.db).add_event(
                event_type="process_remote_result",
                payload={"job_id": job.id},
                idempotency_key=event_key,
            )
        self.db.commit()
        self.db.refresh(result)
        return result

    # ------------------------------------------------------------------
    # User operations
    # ------------------------------------------------------------------

    def list_jobs(
        self,
        *,
        tenant_id: int,
        incident_id: int | None = None,
        status: RemoteJobStatus | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[RemoteJob], int]:
        filters = [RemoteJob.tenant_id == tenant_id]
        if incident_id is not None:
            filters.append(RemoteJob.incident_id == incident_id)
        if status is not None:
            filters.append(RemoteJob.status == status)
        count_stmt = select(func.count()).select_from(RemoteJob).where(*filters)
        total = int(self.db.scalar(count_stmt) or 0)
        jobs = list(
            self.db.scalars(
                select(RemoteJob)
                .where(*filters)
                .order_by(RemoteJob.id.desc())
                .limit(limit)
                .offset(offset)
            ).all()
        )
        return jobs, total

    def get_for_tenant(self, job_id: int, tenant_id: int) -> RemoteJob | None:
        return self.db.scalar(
            select(RemoteJob).where(
                RemoteJob.id == job_id,
                RemoteJob.tenant_id == tenant_id,
            )
        )

    def require_for_tenant(
        self,
        job_id: int,
        tenant_id: int,
        *,
        for_update: bool = False,
    ) -> RemoteJob:
        statement = select(RemoteJob).where(
            RemoteJob.id == job_id,
            RemoteJob.tenant_id == tenant_id,
        )
        if for_update:
            bind = self.db.get_bind()
            if bind is not None and bind.dialect.name == "postgresql":
                statement = statement.with_for_update()
            statement = statement.execution_options(populate_existing=True)
        job = self.db.scalar(statement)
        if job is None:
            raise RemoteJobNotFoundError(job_id)
        return job

    # ------------------------------------------------------------------
    # Recovery
    # ------------------------------------------------------------------

    def recover_expired_leases(self, limit: int = 100) -> int:
        """Recover abandoned leases without replaying uncertain destructive work."""
        now = utcnow()
        statement = (
            select(RemoteJob)
            .where(
                RemoteJob.status.in_(
                    [
                        RemoteJobStatus.DISPATCHED,
                        RemoteJobStatus.ACKNOWLEDGED,
                        RemoteJobStatus.RUNNING,
                    ]
                ),
                RemoteJob.lease_expires_at.is_not(None),
                RemoteJob.lease_expires_at < now,
            )
            .order_by(RemoteJob.id)
            .limit(limit)
        )
        bind = self.db.get_bind()
        if bind is not None and bind.dialect.name == "postgresql":
            statement = statement.with_for_update(skip_locked=True)
        jobs = list(self.db.scalars(statement).all())
        changed = 0
        for job in jobs:
            changed += 1
            job.lease_id = None
            job.lease_expires_at = None
            if job.status == RemoteJobStatus.DISPATCHED:
                if (job.attempt_count or 0) < 3:
                    job.status = RemoteJobStatus.APPROVED
                    job.last_error = "lease expired before acknowledgement; retry queued"
                else:
                    job.status = RemoteJobStatus.EXPIRED
                    job.completed_at = now
                    job.last_error = "lease expired before acknowledgement"
            elif job.execution_type == RemoteExecutionType.REMEDIATION:
                # A destructive command may have started. Never replay it
                # automatically; require human reconciliation.
                job.status = RemoteJobStatus.UNKNOWN
                job.completed_at = now
                job.last_error = "agent disappeared after acknowledgement; outcome unknown"
            elif (job.attempt_count or 0) < 3:
                job.status = RemoteJobStatus.APPROVED
                job.last_error = "lease expired; diagnostic retry queued"
            else:
                job.status = RemoteJobStatus.EXPIRED
                job.completed_at = now
                job.last_error = "lease expired after repeated attempts"
            self._event(
                job,
                "job.lease_recovered",
                details={"new_status": job.status.value},
            )

        if changed:
            self.db.commit()
        return changed

    def expire_unleased_jobs(self, limit: int = 200) -> int:
        now = utcnow()
        statement = (
            select(RemoteJob)
            .where(
                RemoteJob.status.in_(
                    [
                        RemoteJobStatus.PENDING_APPROVAL,
                        RemoteJobStatus.APPROVED,
                    ]
                ),
                RemoteJob.expires_at < now,
            )
            .order_by(RemoteJob.id)
            .limit(limit)
        )
        bind = self.db.get_bind()
        if bind is not None and bind.dialect.name == "postgresql":
            statement = statement.with_for_update(skip_locked=True)
        jobs = list(self.db.scalars(statement).all())
        for job in jobs:
            job.status = RemoteJobStatus.EXPIRED
            job.completed_at = now
            job.last_error = "job expired before dispatch"
            if job.approval is not None and job.approval.status == RemoteApprovalStatus.PENDING:
                job.approval.status = RemoteApprovalStatus.EXPIRED
            self._event(job, "job.expired")
        if jobs:
            self.db.commit()
        return len(jobs)

    def unprocessed_terminal_job_ids(self, limit: int = 200) -> list[int]:
        """Terminal jobs whose investigation result has not been applied yet.

        This is the recovery backstop for a lost Celery wake-up: the periodic
        task can resume any completed/expired/unknown job exactly like an
        outbox-delivered result.
        """
        return list(
            self.db.scalars(
                select(RemoteJob.id)
                .where(
                    RemoteJob.status.in_(REMOTE_TERMINAL_STATUSES),
                    RemoteJob.result_processed_at.is_(None),
                )
                .order_by(RemoteJob.id)
                .limit(limit)
            ).all()
        )

    def has_active_remediation(
        self,
        tenant_id: int,
        incident_id: int,
        *,
        for_update: bool = False,
    ) -> bool:
        """True when a destructive job may still be running on the target.

        On PostgreSQL the start path locks the destructive job row so leasing
        cannot concurrently turn an already-approved destructive job into an
        in-flight one underneath the restart check.
        """
        statement = (
            select(RemoteJob.id)
            .where(
                RemoteJob.tenant_id == tenant_id,
                RemoteJob.incident_id == incident_id,
                RemoteJob.execution_type == RemoteExecutionType.REMEDIATION,
                RemoteJob.status.in_(
                    [
                        RemoteJobStatus.APPROVED,
                        RemoteJobStatus.DISPATCHED,
                        RemoteJobStatus.ACKNOWLEDGED,
                        RemoteJobStatus.RUNNING,
                    ]
                ),
            )
            .limit(1)
        )
        if for_update:
            bind = self.db.get_bind()
            if bind is not None and bind.dialect.name == "postgresql":
                statement = statement.with_for_update()
                statement = statement.execution_options(
                    populate_existing=True
                )
        return self.db.scalar(statement) is not None

    def cancel_pending_for_incident(
        self,
        tenant_id: int,
        incident_id: int,
        *,
        reason: str,
        commit: bool = True,
    ) -> int:
        """Cancel not-yet-leased jobs when an investigation is restarted.

        In-flight jobs are deliberately left alone: changing their state while
        an agent may be executing would turn a known outcome into an unknown
        one. The caller checks ``has_active_remediation`` first.
        """
        now = utcnow()
        statement = select(RemoteJob).where(
            RemoteJob.tenant_id == tenant_id,
            RemoteJob.incident_id == incident_id,
            RemoteJob.status.in_(
                [
                    RemoteJobStatus.PENDING_APPROVAL,
                    RemoteJobStatus.APPROVED,
                ]
            ),
        )
        bind = self.db.get_bind()
        if bind is not None and bind.dialect.name == "postgresql":
            # Another transaction may be approving or leasing one of these
            # rows. Skip it rather than racing the same job.
            statement = statement.with_for_update(skip_locked=True)
        jobs = list(self.db.scalars(statement).all())
        for job in jobs:
            job.status = RemoteJobStatus.CANCELLED
            job.completed_at = now
            job.last_error = reason
            job.result_processed_at = now
            if (
                job.approval is not None
                and job.approval.status == RemoteApprovalStatus.PENDING
            ):
                job.approval.status = RemoteApprovalStatus.EXPIRED
            self._event(
                job,
                "job.cancelled",
                details={"reason": reason},
            )
        if jobs and commit:
            self.db.commit()
        return len(jobs)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_agent_job(
        self,
        *,
        tenant_id: int,
        agent_id: int,
        job_id: int,
        for_update: bool = False,
    ) -> RemoteJob:
        statement = select(RemoteJob).where(
            RemoteJob.id == job_id,
            RemoteJob.tenant_id == tenant_id,
            RemoteJob.agent_id == agent_id,
        )
        if for_update:
            bind = self.db.get_bind()
            if bind is not None and bind.dialect.name == "postgresql":
                statement = statement.with_for_update()
            statement = statement.execution_options(populate_existing=True)
        job = self.db.scalar(statement)
        if job is None:
            raise RemoteJobNotFoundError(job_id)
        if is_expired(job.expires_at) and job.status not in (
            RemoteJobStatus.DISPATCHED,
            RemoteJobStatus.ACKNOWLEDGED,
            RemoteJobStatus.RUNNING,
        ):
            raise RemoteJobExpiredError("job has expired")
        return job

    def _event(
        self,
        job: RemoteJob,
        event_type: str,
        *,
        actor_type: str = "system",
        actor_id: int | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.db.add(
            RemoteJobEvent(
                tenant_id=job.tenant_id,
                job_id=job.id,
                event_type=event_type,
                actor_type=actor_type,
                actor_id=actor_id,
                details=details or {},
            )
        )

    @staticmethod
    def compute_action_hash(job: RemoteJob) -> str:
        return compute_action_hash(
            tenant_id=job.tenant_id,
            incident_id=job.incident_id,
            agent_id=job.agent_id,
            action_id=job.action_id,
            parameters=job.action_parameters or {},
            risk_level=job.risk_level,
        )

    @staticmethod
    def new_job_reference() -> str:
        return uuid.uuid4().hex

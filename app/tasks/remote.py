"""Celery tasks for remote investigation and durable job recovery."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select, text

from app.agent.state import InvestigationState
from app.celery_app import celery_app
from app.database.session import SessionLocal
from app.models.workflow_state import WorkflowState
from app.services.remote_investigation import RemoteInvestigationService
from app.services.remote_job import RemoteJobService

logger = logging.getLogger(__name__)

# Share the local investigation's advisory-lock namespace so a duplicate
# delivery cannot run a remote plan concurrently with another workflow.
_LOCK_NAMESPACE = 20261107


def _try_acquire_lock(db, incident_id: int) -> bool:
    bind = db.get_bind()
    if bind is None or bind.dialect.name != "postgresql":
        return True
    return bool(
        db.execute(
            text("SELECT pg_try_advisory_lock(:namespace, :incident_id)"),
            {"namespace": _LOCK_NAMESPACE, "incident_id": incident_id},
        ).scalar()
    )


def _release_lock(db, incident_id: int) -> None:
    bind = db.get_bind()
    if bind is None or bind.dialect.name != "postgresql":
        return
    try:
        db.execute(
            text("SELECT pg_advisory_unlock(:namespace, :incident_id)"),
            {"namespace": _LOCK_NAMESPACE, "incident_id": incident_id},
        )
        db.commit()
    except Exception:  # noqa: BLE001
        db.rollback()
        logger.exception(
            "Failed to release remote investigation lock for incident %s",
            incident_id,
        )


def _latest_state(db, incident_id: int):
    row = db.scalar(
        select(WorkflowState)
        .where(WorkflowState.incident_id == incident_id)
        .order_by(WorkflowState.id.desc())
        .limit(1)
    )
    if row is None:
        return None
    return row, InvestigationState(**row.state_json)


def _persist_failed(db, state: InvestigationState, message: str) -> None:
    state.workflow_status = "failed"
    state.current_step = "error"
    state.error = message
    state.updated_at = datetime.now(timezone.utc).isoformat()
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


@celery_app.task(name="run_remote_investigation")
def run_remote_investigation(
    incident_id: int,
    actor_user_id: int | None = None,
    actor_email: str = "",
    run_id: str | None = None,
) -> None:
    db = SessionLocal()
    state = None
    lock_acquired = False
    try:
        lock_acquired = _try_acquire_lock(db, incident_id)
        if not lock_acquired:
            logger.info(
                "Remote investigation %s is already running; skipping duplicate",
                incident_id,
            )
            return

        loaded = _latest_state(db, incident_id)
        if loaded is None:
            return
        _, state = loaded
        if run_id and state.run_id and state.run_id != run_id:
            logger.info("Skipping stale remote investigation run %s", run_id)
            return
        if state.workflow_status != "in_progress":
            logger.info(
                "Remote investigation %s is %s; skipping duplicate delivery",
                incident_id,
                state.workflow_status,
            )
            return
        if state.current_step != "load_incident":
            logger.info(
                "Remote investigation %s already started (%s); skipping duplicate",
                incident_id,
                state.current_step,
            )
            return
        service = RemoteInvestigationService(db)
        service.start(state)
    except Exception:  # noqa: BLE001
        logger.exception("Remote investigation %s failed", incident_id)
        if state is not None:
            try:
                _persist_failed(db, state, "Remote investigation failed")
            except Exception:
                db.rollback()
                logger.exception("Could not persist remote investigation failure")
        raise
    finally:
        if lock_acquired:
            _release_lock(db, incident_id)
        db.close()


@celery_app.task(name="process_remote_result")
def process_remote_result(job_id: int) -> None:
    db = SessionLocal()
    try:
        RemoteInvestigationService(db).process_job_result(job_id)
    finally:
        db.close()


@celery_app.task(name="recover_remote_jobs")
def recover_remote_jobs() -> dict[str, int]:
    db = SessionLocal()
    try:
        service = RemoteJobService(db)
        recovered = service.recover_expired_leases()
        expired = service.expire_unleased_jobs()

        # Backstop for a lost broker wake-up or a job that reached a terminal
        # state without an agent result (expired approval, crash-lost lease).
        processed = 0
        investigation = RemoteInvestigationService(db)
        for job_id in service.unprocessed_terminal_job_ids():
            try:
                investigation.process_job_result(job_id)
                processed += 1
            except Exception:  # noqa: BLE001
                logger.exception("Failed to process remote job %s", job_id)
        return {
            "recovered": recovered,
            "expired": expired,
            "processed": processed,
        }
    finally:
        db.close()

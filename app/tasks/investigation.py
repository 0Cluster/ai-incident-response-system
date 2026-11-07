"""Celery task that runs the LangGraph investigation workflow asynchronously.

Running the graph in a Celery task keeps HTTP requests fast while the AI
analysis (which can take minutes) completes in the background.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import text

from app.agent.state import InvestigationState
from app.agent.workflow import (
    get_compiled_approval_workflow,
    get_compiled_workflow,
)
from app.celery_app import celery_app
from app.database.session import SessionLocal
from app.models.workflow_state import WorkflowState

logger = logging.getLogger(__name__)

# Session-level PostgreSQL advisory lock. Duplicate Celery deliveries for the
# same incident must not execute a remediation twice.
_LOCK_NAMESPACE = 20261107


def _persist_state(db, state: InvestigationState) -> None:
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


def _latest_row(db, incident_id: int) -> WorkflowState | None:
    return (
        db.query(WorkflowState)
        .filter(WorkflowState.incident_id == incident_id)
        .order_by(WorkflowState.id.desc())
        .first()
    )


def _load_state(db, incident_id: int) -> InvestigationState | None:
    row = _latest_row(db, incident_id)
    if row is None:
        return None
    return InvestigationState(**row.state_json)


def _run_is_current(
    db,
    incident_id: int,
    run_id: str | None,
) -> bool:
    """Return False when a newer dispatch superseded this worker's run."""
    if not run_id:
        return True
    latest = _load_state(db, incident_id)
    return latest is not None and latest.run_id == run_id


def _try_acquire_lock(db, incident_id: int) -> bool:
    """Return True when this worker owns the investigation lock.

    SQLite (used by unit tests) has no advisory locks, so it is treated as
    always acquired. Production deployments use PostgreSQL.
    """
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
            "Failed to release investigation lock for incident %s",
            incident_id,
        )


@celery_app.task(name="run_investigation")
def run_investigation(
    incident_id: int,
    actor_user_id: int | None = None,
    actor_email: str = "",
    run_id: str | None = None,
    resume: bool = False,
) -> None:
    """Run or resume the LangGraph investigation workflow asynchronously.

    ``resume=True`` is used after human approval and starts the short
    execution graph directly; it never re-runs analysis or planning.
    ``run_id`` belongs to one dispatch attempt. A slow worker whose run has
    been superseded will not overwrite the newer state. Duplicate deliveries
    are ignored when the latest run is already completed or is still waiting
    for a human decision, and a PostgreSQL advisory lock keeps two workers
    from executing the same investigation concurrently.
    """
    db = SessionLocal()
    state: InvestigationState | None = None
    lock_acquired = False
    try:
        lock_acquired = _try_acquire_lock(db, incident_id)
        if not lock_acquired:
            logger.info(
                "Investigation %s is already running; skipping duplicate delivery",
                incident_id,
            )
            return

        state = _load_state(db, incident_id)

        if state is not None:
            if run_id and state.run_id and state.run_id != run_id:
                logger.info(
                    "Investigation %s delivery for run %s is stale (latest %s); "
                    "skipping",
                    incident_id,
                    run_id,
                    state.run_id,
                )
                return
            if state.workflow_status == "completed":
                logger.info(
                    "Investigation %s is already completed; skipping duplicate delivery",
                    incident_id,
                )
                return
            if (
                state.workflow_status == "waiting_for_approval"
                and state.approved is None
            ):
                logger.info(
                    "Investigation %s is already waiting for approval; "
                    "skipping duplicate delivery",
                    incident_id,
                )
                return
            if resume and not (
                state.approved is True and state.requires_approval
            ):
                logger.warning(
                    "Investigation %s resume requested without a valid approval; "
                    "skipping",
                    incident_id,
                )
                return

        if state is None:
            state = InvestigationState(
                incident_id=incident_id,
                tenant_id=1,
                actor_user_id=actor_user_id,
                actor_email=actor_email,
                created_at=datetime.now(timezone.utc).isoformat(),
                updated_at=datetime.now(timezone.utc).isoformat(),
            )

        # Resolve the tenant from the incident when it is available.
        from app.repositories.incident import IncidentRepository

        incident = IncidentRepository(db).get(incident_id)
        if incident is not None:
            state.tenant_id = incident.tenant_id

        state.workflow_status = "in_progress"
        state.updated_at = datetime.now(timezone.utc).isoformat()

        graph = (
            get_compiled_approval_workflow()
            if resume
            else get_compiled_workflow()
        )
        result = graph.invoke(state)

        updated_state = InvestigationState(**result)

        # A forced restart (or a manually dispatched newer run) may have
        # happened while this graph was running. Do not clobber it.
        if not _run_is_current(db, incident_id, run_id):
            logger.info(
                "Discarding stale result for investigation %s run %s",
                incident_id,
                run_id,
            )
            return

        _persist_state(db, updated_state)
    except Exception:  # noqa: BLE001
        logger.exception("Investigation %s failed", incident_id)
        # Persist the failure so the UI stops polling and shows the error,
        # but never let an old run mark a newer run as failed.
        try:
            if state is not None and _run_is_current(db, incident_id, run_id):
                state.workflow_status = "failed"
                state.current_step = "error"
                state.error = "Investigation workflow failed"
                state.updated_at = datetime.now(timezone.utc).isoformat()
                _persist_state(db, state)
        except Exception:  # noqa: BLE001
            db.rollback()
            logger.exception("Could not persist failure state for %s", incident_id)
        raise
    finally:
        if lock_acquired:
            _release_lock(db, incident_id)
        db.close()

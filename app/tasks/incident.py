import logging
import time

from celery.exceptions import SoftTimeLimitExceeded
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.automation.engine import AutomationEngine
from app.celery_app import celery_app
from app.core.providers import get_incident_analyzer
from app.database.session import SessionLocal
from app.models.enums import AnalysisStatus, AutomationStatus, Severity
from app.models.incident import Incident
from app.monitoring.service import MonitoringService
from app.repositories.incident import IncidentRepository

logger = logging.getLogger(__name__)

# Session-level Postgres advisory lock: duplicate deliveries for the same
# incident are dropped instead of running the LLM/automation twice.
_LOCK_NAMESPACE = 20261106


def _try_acquire_lock(db: Session, incident_id: int) -> bool:
    """Acquire a Postgres advisory lock, or no-op on SQLite test databases."""
    bind = db.get_bind()
    if bind is None or bind.dialect.name != "postgresql":
        return True
    return bool(
        db.execute(
            text("SELECT pg_try_advisory_lock(:namespace, :incident_id)"),
            {"namespace": _LOCK_NAMESPACE, "incident_id": incident_id},
        ).scalar()
    )


def _release_lock(db: Session, incident_id: int) -> None:
    bind = db.get_bind()
    if bind is None or bind.dialect.name != "postgresql":
        return
    db.execute(
        text("SELECT pg_advisory_unlock(:namespace, :incident_id)"),
        {"namespace": _LOCK_NAMESPACE, "incident_id": incident_id},
    )
    db.commit()


def processing_plan(incident: Incident) -> tuple[bool, bool]:
    """Return (run_analysis, run_automation) for an at-least-once delivery."""
    run_analysis = incident.analysis_status != AnalysisStatus.COMPLETED
    run_automation = incident.automation_status not in (
        AutomationStatus.SUCCESS,
        AutomationStatus.FAILED,
    )
    return run_analysis, run_automation


def _run_analysis(
    incident: Incident,
    repository: IncidentRepository,
    db: Session,
) -> None:
    incident.analysis_status = AnalysisStatus.RUNNING
    repository.update(incident)

    MonitoringService.analysis_started()
    start = time.perf_counter()

    try:
        analysis = get_incident_analyzer().analyze(
            incident.message,
            tenant_id=incident.tenant_id,
        )
        duration = time.perf_counter() - start

        MonitoringService.analysis_completed(duration)

        incident.ai_summary = analysis.summary
        incident.severity = Severity(analysis.severity)
        incident.recommendation = analysis.recommendation
        incident.analysis_status = AnalysisStatus.COMPLETED
        incident.rag_sources = analysis.sources
        repository.update(incident)

        MonitoringService.incident_completed(incident.severity)
    except Exception:
        MonitoringService.analysis_failed()
        logger.exception("Failed to analyze incident %s", incident.id)

        try:
            db.rollback()
            incident.analysis_status = AnalysisStatus.FAILED
            repository.update(incident)
        except Exception:
            logger.exception("Failed to persist FAILED status")
            db.rollback()

        if incident.severity is not None:
            MonitoringService.incident_failed(incident.severity)
        raise


@celery_app.task(
    bind=True,
    name="analyze_incident",
)
def analyze_incident(self, incident_id: int) -> None:
    logger.info(
        "Analyzing incident %s (task=%s)",
        incident_id,
        self.request.id,
    )

    db: Session = SessionLocal()
    lock_acquired = False

    try:
        lock_acquired = _try_acquire_lock(db, incident_id)
        if not lock_acquired:
            logger.info(
                "Incident %s is already being processed; skipping duplicate delivery",
                incident_id,
            )
            return

        repository = IncidentRepository(db)
        incident = repository.get(incident_id)
        if incident is None:
            return

        run_analysis, run_automation = processing_plan(incident)
        if not run_analysis and not run_automation:
            logger.info(
                "Incident %s is already fully processed; skipping duplicate delivery",
                incident_id,
            )
            return

        if run_analysis:
            try:
                _run_analysis(incident, repository, db)
            except SoftTimeLimitExceeded:
                # The task will be retried by Celery's time-limit handling.
                raise
            except Exception as exc:
                # The outbox event is already PUBLISHED by the dispatcher, so
                # this retry is the only automatic redelivery. The persisted
                # FAILED status makes the retry rerun analysis; completed
                # analysis is never repeated.
                if self.request.retries < self.max_retries:
                    logger.warning(
                        "Analysis failed for incident %s; retrying "
                        "(attempt %s/%s)",
                        incident_id,
                        self.request.retries + 1,
                        self.max_retries,
                    )
                    raise self.retry(exc=exc, countdown=30)
                raise

        # Automation runs after analysis is committed, so an automation
        # failure does not rewrite analysis COMPLETED.
        if run_automation:
            try:
                AutomationEngine().run(incident, db)
            except Exception:
                logger.exception(
                    "Automation failed for incident %s (analysis kept COMPLETED)",
                    incident_id,
                )
                raise
    finally:
        if lock_acquired:
            try:
                _release_lock(db, incident_id)
            except Exception:
                db.rollback()
                logger.exception(
                    "Failed to release advisory lock for incident %s",
                    incident_id,
                )
        db.close()
        logger.info("Finished incident %s", incident_id)

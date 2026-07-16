import logging
import time

from sqlalchemy.orm import Session

from app.ai.analyzer import IncidentAnalyzer
from app.automation.engine import AutomationEngine
from app.celery_app import celery_app
from app.database.session import SessionLocal
from app.models.enums import AnalysisStatus, IncidentStatus, Severity
from app.monitoring.service import MonitoringService
from app.repositories.incident import IncidentRepository

logger = logging.getLogger(__name__)


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

    try:
        repository = IncidentRepository(db)
        analyzer = IncidentAnalyzer()

        incident = repository.get(incident_id)

        if incident is None:
            return

        incident.analysis_status = AnalysisStatus.RUNNING     
        repository.update(incident)

        MonitoringService.analysis_started()

        start = time.perf_counter()

        analysis = analyzer.analyze(
            incident.message,
        )

        duration = time.perf_counter() - start

        MonitoringService.analysis_completed(
            duration,
        )

        incident.ai_summary = analysis.summary
        incident.severity = Severity(analysis.severity)
        incident.recommendation = analysis.recommendation
        incident.analysis_status = AnalysisStatus.COMPLETED

        repository.update(incident)

        MonitoringService.incident_completed(
            incident.severity,
        )

        AutomationEngine().run(
            incident,
            db,
        )

    except Exception:

        MonitoringService.analysis_failed()
        logger.exception(
            "Failed to analyze incident %s",
            incident_id,
        )

        if "incident" in locals() and incident is not None:

            incident.analysis_status = AnalysisStatus.FAILED
            repository.update(incident)

            if incident.severity is not None:
                MonitoringService.incident_failed(
                    incident.severity,
                )

        raise

    finally:
        db.close()

        logger.info(
            "Finished incident %s",
            incident_id,
        )

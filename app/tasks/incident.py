from sqlalchemy.orm import Session

from app.automation.engine import AutomationEngine
from app.ai.analyzer import IncidentAnalyzer
from app.models.enums import IncidentStatus, Severity
from app.database.session import SessionLocal
from app.repositories.incident import IncidentRepository


def analyze_incident(incident_id: int) -> None:
    db: Session = SessionLocal()

    try:
        repository = IncidentRepository(db)
        analyzer = IncidentAnalyzer()

        incident = repository.get(incident_id)

        if incident is None:
            return

        incident.status = IncidentStatus.PROCESSING
        repository.update(incident)

        analysis = analyzer.analyze(incident.message)

        incident.ai_summary = analysis.summary
        incident.severity = Severity(analysis.severity)
        incident.recommendation = analysis.recommendation
        incident.status = IncidentStatus.COMPLETED

        repository.update(incident)

        AutomationEngine().run(
            incident,
            db,
        )

    except Exception:
        if incident is not None:
            incident.status = IncidentStatus.FAILED
            repository.update(incident)

    finally:
        db.close()

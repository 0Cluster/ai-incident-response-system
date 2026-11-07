from app.ai.analyzer import IncidentAnalyzer
from app.models.enums import (
    AnalysisStatus,
    AutomationStatus,
    IncidentSource,
    IncidentStatus,
    Severity,
)
from app.models.incident import Incident
from app.repositories.incident import IncidentRepository
from app.repositories.outbox import OutboxRepository
from app.schemas.incident import IncidentCreate, IncidentUpdate
from app.exceptions.incident import IncidentNotFoundError


class IncidentService:
    def __init__(
        self,
        repository: IncidentRepository,
        analyzer: IncidentAnalyzer,
    ):
        self.repository = repository
        self.analyzer = analyzer

    def create_incident(
        self,
        data: IncidentCreate,
        *,
        tenant_id: int,
        enqueue_analysis: bool = True,
    ) -> Incident:

        incident = Incident(
            tenant_id=tenant_id,
            title=data.title,
            message=data.message,
            status=IncidentStatus.OPEN,
            analysis_status=AnalysisStatus.PENDING,
            automation_status=AutomationStatus.PENDING,
            severity=data.severity,
            source=data.source,
            fingerprint=data.fingerprint,
        )

        db = self.repository.db
        try:
            # Incident + outbox event must commit atomically. Never call
            # .delay() here: a broker outage must not roll back the alert.
            db.add(incident)
            db.flush()
            if enqueue_analysis:
                OutboxRepository(db).add_event(
                    event_type="analyze_incident",
                    payload={"incident_id": incident.id},
                    idempotency_key=f"analyze_incident:{incident.id}",
                )
            db.commit()
            db.refresh(incident)
            return incident
        except Exception:
            db.rollback()
            raise

    def get_incident(self, incident_id: int, tenant_id: int) -> Incident:
        incident = self.repository.get_for_tenant(incident_id, tenant_id)

        if incident is None:
            raise IncidentNotFoundError(incident_id)

        return incident

    def list_incidents(self, tenant_id: int) -> list[Incident]:
        return self.repository.list_filtered(tenant_id=tenant_id, limit=10_000)[0]

    def list_filtered(
        self,
        *,
        tenant_id: int,
        status: IncidentStatus | None = None,
        severity: Severity | None = None,
        source: IncidentSource | None = None,
        query: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Incident], int]:
        return self.repository.list_filtered(
            status=status,
            severity=severity,
            source=source,
            query=query,
            tenant_id=tenant_id,
            limit=limit,
            offset=offset,
        )

    def stats(
        self,
        *,
        tenant_id: int,
        status: IncidentStatus | None = None,
        severity: Severity | None = None,
        source: IncidentSource | None = None,
        query: str | None = None,
    ) -> tuple[int, dict[str, int], dict[str, int]]:
        return self.repository.stats_filtered(
            status=status,
            severity=severity,
            source=source,
            query=query,
            tenant_id=tenant_id,
        )

    def update_incident(
        self,
        incident_id: int,
        data: IncidentUpdate,
        tenant_id: int,
    ) -> Incident:
        incident = self.repository.get_for_tenant(incident_id, tenant_id)

        if incident is None:
            raise IncidentNotFoundError(incident_id)

        updates = data.model_dump(exclude_unset=True)

        for field, value in updates.items():
            setattr(incident, field, value)

        return self.repository.update(incident)

    def delete_incident(self, incident_id: int, tenant_id: int) -> None:
        incident = self.repository.get_for_tenant(incident_id, tenant_id)

        if incident is None:
            raise IncidentNotFoundError(incident_id)

        self.repository.delete(incident)

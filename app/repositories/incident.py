from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.enums import IncidentStatus, IncidentSource, Severity
from app.models.incident import Incident
from app.repositories.base import BaseRepository


class IncidentRepository(BaseRepository[Incident]):
    def __init__(self, db: Session):
        super().__init__(db, Incident)

    def get_for_tenant(
        self,
        incident_id: int,
        tenant_id: int,
    ) -> Incident | None:
        return (
            self.db.query(Incident)
            .filter(
                Incident.id == incident_id,
                Incident.tenant_id == tenant_id,
            )
            .one_or_none()
        )

    def find_active_by_fingerprint(
        self,
        fingerprint: str,
        tenant_id: int | None = None,
    ) -> Incident | None:

        query = (
            self.db.query(Incident)
            .filter(
                Incident.fingerprint == fingerprint,
                Incident.status.notin_(
                    [IncidentStatus.RESOLVED, IncidentStatus.CLOSED]
                ),
            )
        )
        if tenant_id is not None:
            query = query.filter(Incident.tenant_id == tenant_id)
        return query.first()

    def get_by_title(self, title: str) -> Incident | None:
        statement = select(Incident).where(Incident.title == title)
        result = self.db.execute(statement)
        return result.scalar_one_or_none()

    def get_latest(self, limit: int = 10) -> list[Incident]:
        statement = (
            select(Incident)
            .order_by(Incident.id.desc())
            .limit(limit)
        )

        result = self.db.execute(statement)
        return list(result.scalars().all())

    def search(self, keyword: str, limit: int = 50) -> list[Incident]:
        escaped = keyword.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        statement = (
            select(Incident)
            .where(
                Incident.title.ilike(f"%{escaped}%", escape="\\")
                | Incident.message.ilike(f"%{escaped}%", escape="\\")
            )
            .order_by(Incident.id.desc())
            .limit(limit)
        )

        result = self.db.execute(statement)
        return list(result.scalars().all())

    def _filters(
        self,
        status: IncidentStatus | None = None,
        severity: Severity | None = None,
        source: IncidentSource | None = None,
        query: str | None = None,
        tenant_id: int | None = None,
    ) -> list:
        filters = []
        if tenant_id is not None:
            filters.append(Incident.tenant_id == tenant_id)
        if status is not None:
            filters.append(Incident.status == status)
        if severity is not None:
            filters.append(Incident.severity == severity)
        if source is not None:
            filters.append(Incident.source == source)
        if query:
            escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            filters.append(
                Incident.title.ilike(f"%{escaped}%", escape="\\")
                | Incident.message.ilike(f"%{escaped}%", escape="\\")
            )
        return filters

    def list_filtered(
        self,
        status: IncidentStatus | None = None,
        severity: Severity | None = None,
        source: IncidentSource | None = None,
        query: str | None = None,
        tenant_id: int | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Incident], int]:
        filters = self._filters(status, severity, source, query, tenant_id)

        count_stmt = select(func.count()).select_from(Incident)
        if filters:
            count_stmt = count_stmt.where(*filters)
        total = self.db.execute(count_stmt).scalar_one()

        stmt = select(Incident).order_by(Incident.id.desc())
        if filters:
            stmt = stmt.where(*filters)
        stmt = stmt.limit(limit).offset(offset)
        result = self.db.execute(stmt)
        return list(result.scalars().all()), total

    def stats_filtered(
        self,
        status: IncidentStatus | None = None,
        severity: Severity | None = None,
        source: IncidentSource | None = None,
        query: str | None = None,
        tenant_id: int | None = None,
    ) -> tuple[int, dict[str, int], dict[str, int]]:
        filters = self._filters(status, severity, source, query, tenant_id)

        total_stmt = select(func.count()).select_from(Incident)
        if filters:
            total_stmt = total_stmt.where(*filters)
        total = self.db.execute(total_stmt).scalar_one()

        by_status: dict[str, int] = {}
        stmt = select(Incident.status, func.count()).select_from(Incident)
        if filters:
            stmt = stmt.where(*filters)
        for st, cnt in self.db.execute(stmt.group_by(Incident.status)).all():
            key = st.value if hasattr(st, "value") else str(st)
            by_status[key] = int(cnt)

        by_severity: dict[str, int] = {}
        stmt = select(Incident.severity, func.count()).select_from(Incident)
        if filters:
            stmt = stmt.where(*filters)
        for sev, cnt in self.db.execute(stmt.group_by(Incident.severity)).all():
            key = sev.value if hasattr(sev, "value") else str(sev) if sev else "UNKNOWN"
            by_severity[key] = int(cnt)

        return total, by_status, by_severity

    def update(self, incident: Incident) -> Incident:
        self.db.commit()
        self.db.refresh(incident)
        return incident

    def delete_by_id(
        self,
        incident_id: int,
        tenant_id: int | None = None,
    ) -> bool:
        incident = (
            self.get_for_tenant(incident_id, tenant_id)
            if tenant_id is not None
            else self.get(incident_id)
        )

        if incident is None:
            return False

        self.db.delete(incident)
        self.db.commit()
        return True

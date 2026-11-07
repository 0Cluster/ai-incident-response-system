from sqlalchemy.orm import Session

from app.models.automation_run import AutomationRun


class AutomationRunRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, run: AutomationRun) -> AutomationRun:
        try:
            self.db.add(run)
            self.db.commit()
            self.db.refresh(run)
            return run
        except Exception:
            self.db.rollback()
            raise

    def list_by_incident(
        self,
        incident_id: int,
        tenant_id: int | None = None,
    ) -> list[AutomationRun]:
        query = self.db.query(AutomationRun).filter(
            AutomationRun.incident_id == incident_id
        )
        if tenant_id is not None:
            query = query.filter(AutomationRun.tenant_id == tenant_id)
        return query.order_by(AutomationRun.executed_at.desc()).all()

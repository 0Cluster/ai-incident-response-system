from sqlalchemy.orm import Session

from app.models.automation_run import AutomationRun
from app.repositories.automation_run import AutomationRunRepository


class AutomationRunService:
    def __init__(self, db: Session):
        self.repository = AutomationRunRepository(db)

    def log(
        self,
        incident_id: int,
        action_name: str,
        status: str,
        message: str,
        *,
        tenant_id: int,
    ) -> AutomationRun:

        run = AutomationRun(
            tenant_id=tenant_id,
            incident_id=incident_id,
            action_name=action_name,
            status=status,
            message=message,
        )

        return self.repository.create(run)

    def list_by_incident(
        self,
        incident_id: int,
        tenant_id: int,
    ) -> list[AutomationRun]:
        return self.repository.list_by_incident(incident_id, tenant_id)

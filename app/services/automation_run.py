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
    ) -> AutomationRun:

        run = AutomationRun(
            incident_id=incident_id,
            action_name=action_name,
            status=status,
            message=message,
        )

        return self.repository.create(run)

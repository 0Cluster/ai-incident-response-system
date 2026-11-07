from sqlalchemy.orm import Session

from app.automation.base import AutomationAction
from app.services.automation_run import AutomationRunService
from app.models.incident import Incident


class LogAction(AutomationAction):
    def __init__(
        self,
        action_name: str,
        **kwargs,
    ) -> None:
        self.action_name = action_name

    def execute(
        self,
        incident: Incident,
        db: Session,
    ) -> None:
        print("=" * 50)
        print("[LOG ACTION]")
        print(f"Incident #{incident.id}")
        print(f"Severity: {incident.severity}")
        print("=" * 50)

        AutomationRunService(db).log(
            tenant_id=incident.tenant_id,
            incident_id=incident.id,
            action_name=self.action_name,
            status="SUCCESS",
            message="Incident logged successfully.",
        )

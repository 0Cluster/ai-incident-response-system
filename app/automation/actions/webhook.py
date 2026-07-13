import httpx
from sqlalchemy.orm import Session

from app.automation.base import AutomationAction
from app.models.incident import Incident
from app.monitoring.service import MonitoringService
from app.services.automation_run import AutomationRunService


class WebhookAction(AutomationAction):

    def __init__(
        self,
        action_name: str,
        url: str,
    ) -> None:
        self.action_name = action_name
        self.url = url

    def execute(
        self,
        incident: Incident,
        db: Session,
    ) -> None:

        payload = {
            "id": incident.id,
            "title": incident.title,
            "message": incident.message,
            "summary": incident.ai_summary,
            "severity": incident.severity.value if incident.severity else None,
            "status": incident.status.value,
            "recommendation": incident.recommendation,
        }

        print("=" * 50)
        print("[WEBHOOK ACTION]")
        print(f"Action: {self.action_name}")
        print(f"Incident: {incident.id}")
        print(f"POST {self.url}")
        print("=" * 50)

        try:

            response = httpx.post(
                self.url,
                json=payload,
                timeout=10,
            )

            response.raise_for_status()

            MonitoringService.webhook_success()

            AutomationRunService(db).log(
                incident_id=incident.id,
                action_name=self.action_name,
                status="SUCCESS",
                message=f"HTTP {response.status_code}",
            )

            print(f"Status Code: {response.status_code}")

        except Exception as e:

            MonitoringService.webhook_failure()

            AutomationRunService(db).log(
                incident_id=incident.id,
                action_name=self.action_name,
                status="FAILED",
                message=str(e),
            )

            print(f"Webhook Error: {e}")

            raise

        print("=" * 50)

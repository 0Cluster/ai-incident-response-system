import httpx

from app.models.incident import Incident
from app.automation.base import AutomationAction

class WebhookAction(AutomationAction):
    def __init__(self, url: str):
        self.url = url

    def execute(self, incident: Incident) -> None:
        print("=" * 50)
        print("[WEBHOOK]")
        print("Sending request...")

        payload = {
            "id": incident.id,
            "title": incident.title,
            "message": incident.message,
            "summary": incident.ai_summary,
            "severity": str(incident.severity),
            "status": str(incident.status),
            "recommendation": incident.recommendation,
        }

        try:
            response = httpx.post(
                self.url,
                json=payload,
                timeout=10,
            )

            print(f"Status Code: {response.status_code}")
            print(response.text[:200])

        except Exception as e:
            print(f"Webhook failed: {e}")

        print("=" * 50)

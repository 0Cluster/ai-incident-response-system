from app.models.incident import Incident
from app.automation.base import AutomationAction

class LogAction(AutomationAction):
    def execute(self, incident: Incident) -> None:
        print("=" * 50)
        print("[LOG ACTION]")
        print(f"Incident: {incident.id}")
        print(f"Title: {incident.title}")
        print(f"Severity: {incident.severity}")
        print(f"Status: {incident.status}")
        print("=" * 50)

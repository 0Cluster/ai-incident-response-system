"""Example custom action: post incident alerts to Slack incoming webhook.

How to add your own custom action:
1. Create `app/automation/actions/<name>.py` subclassing `AutomationAction`
   with `__init__(self, action_name: str, ...)` and
   `execute(self, incident, db) -> None`.
2. Register it in `app/automation/registry.py`:
   `registry.register("slack", SlackAction)`.
3. Create a DB rule via API/UI with `action_name="slack"` and matching
   config — engine + metrics + `/actions` list pick it up automatically.
"""
import httpx
from sqlalchemy.orm import Session

from app.automation.base import AutomationAction
from app.models.incident import Incident
from app.services.automation_run import AutomationRunService


class SlackAction(AutomationAction):
    def __init__(
        self,
        action_name: str,
        url: str,
        channel: str | None = None,
        timeout: int = 10,
    ) -> None:
        if not url or not url.strip():
            raise ValueError("url must be a non-empty string")
        self.action_name = action_name
        self.url = url
        self.channel = channel
        self.timeout = timeout

    def execute(
        self,
        incident: Incident,
        db: Session,
    ) -> None:
        sev = incident.severity.value if incident.severity else "UNKNOWN"
        text = f"[{sev}] #{incident.id} {incident.title}\n{incident.ai_summary or incident.message}"
        payload: dict = {"text": text}
        if self.channel:
            payload["channel"] = self.channel
        try:
            resp = httpx.post(self.url, json=payload, timeout=self.timeout)
            resp.raise_for_status()
            AutomationRunService(db).log(
                tenant_id=incident.tenant_id,
                incident_id=incident.id,
                action_name=self.action_name,
                status="SUCCESS",
                message=f"HTTP {resp.status_code}",
            )
        except Exception as e:
            AutomationRunService(db).log(
                tenant_id=incident.tenant_id,
                incident_id=incident.id,
                action_name=self.action_name,
                status="FAILED",
                message=str(e),
            )
            raise

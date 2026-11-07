from unittest.mock import MagicMock, patch

from app.automation.actions.webhook import WebhookAction
from app.models.enums import IncidentStatus, Severity


def make_incident():
    m = MagicMock()
    m.id = 1
    m.title = "t"
    m.message = "m"
    m.ai_summary = "s"
    m.severity = Severity.CRITICAL
    m.status = IncidentStatus.OPEN
    m.recommendation = "r"
    return m


def test_webhook_sends_custom_headers():
    action = WebhookAction(
        action_name="webhook", url="https://n8n/webhook", headers={"X-n8n-Key": "secret"}
    )
    with patch("app.automation.actions.webhook.httpx.post") as post:
        resp = MagicMock()
        resp.status_code = 200
        post.return_value = resp
        action.execute(make_incident(), MagicMock())
        _, kwargs = post.call_args
        assert kwargs["headers"] == {"X-n8n-Key": "secret"}

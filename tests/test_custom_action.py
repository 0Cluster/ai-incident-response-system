from unittest.mock import MagicMock, patch

from app.automation.registry import registry
from app.models.enums import Severity


def test_custom_action_registered_and_runs():
    assert registry.get("slack") is not None
    assert "slack" in registry.list()

    from app.automation.engine import AutomationEngine
    from app.models.automation_rule import AutomationRule

    incident = MagicMock()
    incident.id = 1
    incident.tenant_id = 1
    incident.severity = Severity.HIGH

    from app.automation import engine as engine_mod

    orig = engine_mod.AutomationRuleService.get_actions
    engine_mod.AutomationRuleService.get_actions = lambda self, sev, tenant_id: [
        AutomationRule(
            tenant_id=tenant_id,
            severity="HIGH",
            action_name="slack",
            enabled=True,
            execution_order=1,
            config={"url": "https://hooks.slack.test/x"},
        )
    ]
    try:
        with patch("app.automation.actions.slack.httpx.post") as post:
            resp = MagicMock()
            resp.status_code = 200
            post.return_value = resp
            db = MagicMock()
            AutomationEngine().run(incident, db)
            assert post.called
            body = post.call_args[1]["json"]
            assert "text" in body
    finally:
        engine_mod.AutomationRuleService.get_actions = orig

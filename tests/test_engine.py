from unittest.mock import MagicMock

import pytest

from app.automation.engine import AutomationEngine
from app.models.automation_rule import AutomationRule
from app.models.enums import Severity


def make_incident():
    m = MagicMock()
    m.id = 1
    m.tenant_id = 1
    m.severity = Severity.HIGH
    m.automation_status = None
    return m


def test_continue_on_failure_runs_remaining_rules():
    from app.automation import engine as engine_mod
    from app.automation.actions.log import LogAction

    calls: list[str] = []
    orig = LogAction.execute

    def flaky(self, incident, db):
        calls.append(self.action_name)
        if len(calls) == 1:
            raise RuntimeError("boom")

    LogAction.execute = flaky
    orig_actions = engine_mod.AutomationRuleService.get_actions
    try:
        svc_cls = engine_mod.AutomationRuleService
        svc_cls.get_actions = lambda self, sev, tenant_id: [
            AutomationRule(tenant_id=tenant_id, severity="HIGH", action_name="log", enabled=True, execution_order=1,
                           config={"continue_on_failure": True}),
            AutomationRule(tenant_id=tenant_id, severity="HIGH", action_name="log", enabled=True, execution_order=2, config={}),
        ]
        db = MagicMock()
        AutomationEngine().run(make_incident(), db)
        assert calls == ["log", "log"]
    finally:
        LogAction.execute = orig
        engine_mod.AutomationRuleService.get_actions = orig_actions


def test_rule_validation():
    from app.services.automation_rule import AutomationRuleService

    svc = AutomationRuleService(MagicMock())
    with pytest.raises(ValueError):
        svc.create_rule(
            tenant_id=1,
            severity="HIGH",
            action_name="webhook",
            config={},
        )
    with pytest.raises(ValueError):
        svc.create_rule(
            tenant_id=1,
            severity="HIGH",
            action_name="script",
            config={},
        )
    with pytest.raises(ValueError):
        svc.create_rule(
            tenant_id=1,
            severity="HIGH",
            action_name="slack",
            config={},
        )
    with pytest.raises(ValueError):
        svc.create_rule(
            tenant_id=1,
            severity="NOT_A_SEVERITY",
            action_name="log",
            config={},
        )


def test_update_rule_validates_config_before_mutating():
    from app.services.automation_rule import AutomationRuleService

    rule = AutomationRule(
        tenant_id=1,
        severity="HIGH",
        action_name="webhook",
        enabled=True,
        execution_order=1,
        config={"url": "https://example.test/hook"},
    )
    svc = AutomationRuleService(MagicMock())
    svc.repository.get = lambda *_: rule
    svc.repository.update = MagicMock(return_value=rule)

    with pytest.raises(ValueError):
        svc.update_rule(1, tenant_id=1, config={})

    assert rule.config == {"url": "https://example.test/hook"}
    svc.repository.update.assert_not_called()

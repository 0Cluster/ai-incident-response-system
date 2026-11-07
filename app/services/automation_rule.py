from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.automation_rule import AutomationRule
from app.models.enums import Severity
from app.repositories.automation_rule import AutomationRuleRepository


def seed_default_rules(db: Session, tenant_id: int) -> int:
    """Add missing default log rules for a tenant (no commit)."""
    existing = set(
        db.scalars(
            select(AutomationRule.severity).where(
                AutomationRule.tenant_id == tenant_id,
                AutomationRule.action_name == "log",
            )
        ).all()
    )
    created = 0
    for severity in Severity:
        if severity.value in existing:
            continue
        db.add(
            AutomationRule(
                tenant_id=tenant_id,
                severity=severity.value,
                action_name="log",
                enabled=True,
                execution_order=1,
                config={},
            )
        )
        created += 1
    return created


class AutomationRuleService:
    def __init__(self, db: Session):
        self.db = db
        self.repository = AutomationRuleRepository(db)

    @staticmethod
    def _validate_severity(severity: str) -> str:
        try:
            return Severity(str(severity).upper()).value
        except ValueError as exc:
            allowed = ", ".join(s.value for s in Severity)
            raise ValueError(f"severity must be one of: {allowed}") from exc

    @staticmethod
    def _validate_config(action_name: str, config: dict) -> None:
        """Validate the same contract on create and update.

        Unknown/custom actions are allowed; their own constructor is the
        source of truth when the engine instantiates them.
        """
        if not isinstance(config, dict):
            raise ValueError("config must be a JSON object")

        if action_name in ("webhook", "slack"):
            url = str(config.get("url", "")).strip()
            if not url:
                raise ValueError(f"{action_name} rules require config.url")
            if not url.startswith(("http://", "https://")):
                raise ValueError(f"{action_name} config.url must be http(s)")
        if action_name == "script":
            path = str(config.get("script_path", "")).strip()
            if not path:
                raise ValueError("script rules require config.script_path")

    def get_actions(self, severity: str, tenant_id: int):
        return self.repository.get_enabled(severity, tenant_id)

    def list_rules(self, tenant_id: int) -> list[AutomationRule]:
        return self.repository.list_all(tenant_id)

    def create_rule(
        self,
        tenant_id: int,
        severity: str,
        action_name: str,
        enabled: bool = True,
        execution_order: int = 1,
        config: dict | None = None,
    ) -> AutomationRule:
        cfg = config or {}
        severity = self._validate_severity(severity)
        self._validate_config(action_name, cfg)
        rule = AutomationRule(
            tenant_id=tenant_id,
            severity=severity,
            action_name=action_name,
            enabled=enabled,
            execution_order=execution_order,
            config=cfg,
        )
        return self.repository.create(rule)

    def update_rule(
        self,
        rule_id: int,
        tenant_id: int,
        severity: str | None = None,
        action_name: str | None = None,
        enabled: bool | None = None,
        execution_order: int | None = None,
        config: dict | None = None,
    ) -> AutomationRule | None:
        rule = self.repository.get(rule_id, tenant_id)
        if rule is None:
            return None

        next_severity = (
            self._validate_severity(severity) if severity is not None else None
        )
        clean_action = action_name.strip() if action_name is not None else None
        if clean_action is not None and not clean_action:
            raise ValueError("action_name must not be empty")
        next_action = clean_action or rule.action_name

        if config is not None or next_action != rule.action_name:
            # Validate before mutating ORM state; an invalid config must not
            # be committed during request teardown.
            self._validate_config(
                next_action,
                rule.config if config is None else config,
            )

        if next_severity is not None:
            rule.severity = next_severity
        if clean_action is not None:
            rule.action_name = clean_action
        if enabled is not None:
            rule.enabled = enabled
        if execution_order is not None:
            rule.execution_order = execution_order
        if config is not None:
            rule.config = config
        return self.repository.update(rule)

    def delete_rule(self, rule_id: int, tenant_id: int) -> bool:
        rule = self.repository.get(rule_id, tenant_id)
        if rule is None:
            return False
        self.repository.delete(rule)
        return True

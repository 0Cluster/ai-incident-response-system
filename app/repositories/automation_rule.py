from sqlalchemy.orm import Session

from app.models.automation_rule import AutomationRule


class AutomationRuleRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_enabled(
        self,
        severity: str,
        tenant_id: int,
    ) -> list[AutomationRule]:
        return (
            self.db.query(AutomationRule)
            .filter(
                AutomationRule.tenant_id == tenant_id,
                AutomationRule.severity == severity,
                AutomationRule.enabled.is_(True),
            )
            .order_by(AutomationRule.execution_order)
            .all()
        )

    def list_all(self, tenant_id: int) -> list[AutomationRule]:
        return (
            self.db.query(AutomationRule)
            .filter(AutomationRule.tenant_id == tenant_id)
            .order_by(
                AutomationRule.severity,
                AutomationRule.execution_order,
            )
            .all()
        )

    def get(
        self,
        rule_id: int,
        tenant_id: int,
    ) -> AutomationRule | None:
        return (
            self.db.query(AutomationRule)
            .filter(
                AutomationRule.id == rule_id,
                AutomationRule.tenant_id == tenant_id,
            )
            .one_or_none()
        )

    def create(self, rule: AutomationRule) -> AutomationRule:
        self.db.add(rule)
        self.db.commit()
        self.db.refresh(rule)
        return rule

    def update(self, rule: AutomationRule) -> AutomationRule:
        self.db.commit()
        self.db.refresh(rule)
        return rule

    def delete(self, rule: AutomationRule) -> None:
        self.db.delete(rule)
        self.db.commit()

from sqlalchemy.orm import Session

from app.models.automation_rule import AutomationRule


class AutomationRuleRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_enabled(self, severity: str) -> list[AutomationRule]:
        return (
            self.db.query(AutomationRule)
            .filter(
                AutomationRule.severity == severity,
                AutomationRule.enabled.is_(True),
            )
            .order_by(AutomationRule.execution_order)
            .all()
        )

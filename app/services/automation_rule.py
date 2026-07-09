from sqlalchemy.orm import Session

from app.repositories.automation_rule import AutomationRuleRepository


class AutomationRuleService:
    def __init__(self, db: Session):
        self.repository = AutomationRuleRepository(db)

    def get_actions(self, severity: str):
        return self.repository.get_enabled(severity)

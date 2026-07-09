from sqlalchemy.orm import Session

from app.automation.registry import registry
from app.models.incident import Incident
from app.services.automation_rule import AutomationRuleService


class AutomationEngine:
    def run(
        self,
        incident: Incident,
        db: Session,
    ) -> None:

        rules = AutomationRuleService(db).get_actions(
            incident.severity.value,
        )

        for rule in rules:
            action_class = registry.get(rule.action_name)

            if action_class is None:
                print(f"Unknown action: {rule.action_name}")
                continue

            action = action_class(
                action_name=rule.action_name,
                **rule.config,
            )

            action.execute(
                incident,
                db,
            )

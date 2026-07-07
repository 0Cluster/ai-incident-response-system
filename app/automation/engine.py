from app.automation.registry import registry
from app.automation.rules import RULES
from app.models.incident import Incident


class AutomationEngine:
    def run(self, incident: Incident) -> None:
        actions = RULES.get(incident.severity, [])

        for action_name in actions:
            action = registry.get(action_name)

            if action is None:
                print(f"Unknown action: {action_name}")
                continue

            action.execute(incident)

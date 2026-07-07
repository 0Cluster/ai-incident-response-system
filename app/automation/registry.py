from app.automation.base import AutomationAction
from app.automation.actions.log import LogAction
from app.automation.actions.webhook import WebhookAction


class ActionRegistry:
    def __init__(self) -> None:
        self._actions: dict[str, AutomationAction] = {}

    def register(self, name: str, action: AutomationAction) -> None:
        self._actions[name] = action

    def get(self, name: str) -> AutomationAction | None:
        return self._actions.get(name)

    def list(self) -> list[str]:
        return list(self._actions.keys())


# Create the singleton registry
registry = ActionRegistry()

# Register all built-in actions
registry.register("log", LogAction())
registry.register(
    "webhook",
    WebhookAction("https://httpbin.org/post"),
)

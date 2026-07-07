from abc import ABC, abstractmethod

from app.models.incident import Incident


class AutomationAction(ABC):
    @abstractmethod
    def execute(self, incident: Incident) -> None:
        pass

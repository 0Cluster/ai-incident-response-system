from abc import ABC, abstractmethod

from sqlalchemy.orm import Session

from app.models.incident import Incident


class AutomationAction(ABC):

    @abstractmethod
    def execute(
        self,
        incident: Incident,
        db: Session,
    ) -> None:
        pass

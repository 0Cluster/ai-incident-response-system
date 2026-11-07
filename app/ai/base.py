from abc import ABC, abstractmethod

from app.ai.schemas import IncidentAnalysis


class BaseAnalyzer(ABC):
    @abstractmethod
    def analyze(
        self,
        message: str,
        *,
        tenant_id: int | None = None,
    ) -> IncidentAnalysis:
        raise NotImplementedError

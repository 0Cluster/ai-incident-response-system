from pydantic import BaseModel

from app.models.enums import Severity


class IncidentAnalysis(BaseModel):

    summary: str

    severity: Severity

    recommendation: str

    sources: list[str] = []

    confidence: float | None = None

    model: str | None = None

    abstained: bool = False

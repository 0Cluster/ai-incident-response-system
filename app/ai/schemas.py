from pydantic import BaseModel

from app.models.enums import Severity


class IncidentAnalysis(BaseModel):

    summary: str

    severity: Severity

    recommendation: str

    sources: list[str] = []

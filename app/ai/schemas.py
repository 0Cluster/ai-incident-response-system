from pydantic import BaseModel


class IncidentAnalysis(BaseModel):
    summary: str
    severity: str
    recommendation: str

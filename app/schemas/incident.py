from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import IncidentStatus, Severity

class IncidentCreate(BaseModel):
    title: str = Field(..., min_length=3, max_length=255)
    message: str = Field(..., min_length=1)


class IncidentResponse(BaseModel):
    id: int
    title: str
    message: str

    status: IncidentStatus
    severity: Severity | None

    ai_summary: str | None
    recommendation: str | None

    model_config = ConfigDict(from_attributes=True)


class IncidentUpdate(BaseModel):
    title: str | None = None
    message: str | None = None
